"""suggest

Reads a repository and suggests the infrastructure code it needs: least-privilege IAM
actions derived from real SDK calls, a CI OIDC role pinned to this repo, and
environment/package fixes. Deterministic: nothing here calls an LLM. The Duo agent
reviews and refines the output, and the InfraSec gate reviews what gets merged.

Design rules:
  * Never emit a wildcard ("*") resource. Resources are Terraform variables the user
    must fill in, so a missing value fails loudly instead of granting everything.
  * Every suggestion carries evidence (file:line) so a reviewer can check it.
  * Anything derived by naming convention (not on the verified list) is marked
    confidence "check".
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".terraform",
             "suggested-infra", "tests", "demo-target", "dist", "build", ".tox"}

KNOWN_SERVICES = {"s3", "dynamodb", "sqs", "sns", "secretsmanager", "lambda", "kms", "ssm", "logs"}
IAM_PREFIX = {"bedrock-runtime": "bedrock", "secrets-manager": "secretsmanager",
              "stepfunctions": "states", "sfn": "states", "cloudwatch-logs": "logs"}
ACTION_OVERRIDES = {
    ("s3", "list_objects_v2"): "ListBucket", ("s3", "list_objects"): "ListBucket",
    ("s3", "upload_file"): "PutObject", ("s3", "upload_fileobj"): "PutObject",
    ("s3", "download_file"): "GetObject", ("s3", "download_fileobj"): "GetObject",
    ("s3", "head_object"): "GetObject", ("lambda", "invoke"): "InvokeFunction",
}
NON_API = {"get_paginator", "can_paginate", "get_waiter", "generate_presigned_url", "close",
           "meta", "exceptions", "Table", "Bucket", "Queue", "Topic", "Object"}
RESOURCE_CTORS = {"Table", "Bucket", "Queue", "Topic", "Object"}
SECRET_NAME = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|PRIVATE_?KEY|CREDENTIAL)", re.I)
AMBIENT_ENV = re.compile(r"^(AWS_|LAMBDA_|_HANDLER|PATH$|HOME$|PWD$|HOSTNAME$|LANG$|TZ$)")


@dataclass
class Usage:
    service: str
    action: str          # IAM action without prefix, e.g. GetObject
    file: str
    line: int
    confidence: str      # "high" | "check"

    @property
    def iam(self) -> str:
        return f"{IAM_PREFIX.get(self.service, self.service)}:{self.action}"


@dataclass
class Finding:
    code: str
    severity: str        # "info" | "warn" | "critical"
    message: str
    evidence: list[str] = field(default_factory=list)
    fix: str = ""


@dataclass
class Suggestion:
    files: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    usages: list[Usage] = field(default_factory=list)
    env_vars: dict[str, list[str]] = field(default_factory=dict)
    repo: Optional[str] = None


def _pascal(snake: str) -> str:
    return "".join(p.capitalize() for p in snake.split("_"))


def _walk(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not (set(p.relative_to(root).parts[:-1]) & SKIP_DIRS):
            yield p


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ------------------------------------------------------------------ python SDK usage
def _name(node) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _service_of(call: ast.Call, tracked: dict[str, str]) -> Optional[str]:
    f = call.func
    if not isinstance(f, ast.Attribute):
        return None
    if f.attr in ("client", "resource") and call.args and isinstance(call.args[0], ast.Constant) \
            and isinstance(call.args[0].value, str):
        return call.args[0].value
    if f.attr in RESOURCE_CTORS:
        recv = _name(f.value)
        if recv in tracked:
            return tracked[recv]
        if isinstance(f.value, ast.Call):
            return _service_of(f.value, tracked)
    return None


def _scan_python(path: Path, rel: str, usages: list, envs: dict):
    try:
        tree = ast.parse(_read(path))
    except SyntaxError:
        return
    tracked: dict[str, str] = {}
    for _ in range(2):  # second pass resolves variables derived from other variables
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                svc = _service_of(node.value, tracked)
                if svc:
                    for t in node.targets:
                        n = _name(t)
                        if n:
                            tracked[n] = svc
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            method, recv = node.func.attr, node.func.value
            svc = tracked.get(_name(recv) or "") or (_service_of(recv, tracked) if isinstance(recv, ast.Call) else None)
            if svc and method not in NON_API - {"get_paginator"}:
                if method == "get_paginator":
                    if not (node.args and isinstance(node.args[0], ast.Constant)):
                        continue
                    method = node.args[0].value
                action = ACTION_OVERRIDES.get((svc, method)) or _pascal(method)
                conf = "high" if svc in KNOWN_SERVICES else "check"
                usages.append(Usage(svc, action, rel, node.lineno, conf))
        # environment variables
        name = None
        if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ" \
                and isinstance(node.slice, ast.Constant):
            name = node.slice.value
        elif isinstance(node, ast.Call) and ast.unparse(node.func) in ("os.environ.get", "os.getenv") \
                and node.args and isinstance(node.args[0], ast.Constant):
            name = node.args[0].value
        if isinstance(name, str):
            envs.setdefault(name, []).append(f"{rel}:{node.lineno}")


# ------------------------------------------------------------------ javascript SDK usage
JS_IMPORT = re.compile(r"""(?:import\s*\{([^}]*)\}\s*from|const\s*\{([^}]*)\}\s*=\s*require\()\s*["']@aws-sdk/client-([a-z0-9-]+)["']""")
JS_ENV = re.compile(r"process\.env\.([A-Z0-9_]+)")


def _scan_js(path: Path, rel: str, usages: list, envs: dict):
    text = _read(path)
    for m in JS_IMPORT.finditer(text):
        svc = m.group(3)
        line = text.count("\n", 0, m.start()) + 1
        for raw in (m.group(1) or m.group(2) or "").split(","):
            name = raw.strip().split(" as ")[0].strip()
            if name.endswith("Command") and len(name) > 7:
                usages.append(Usage(svc, name[:-7], rel, line, "high" if svc in KNOWN_SERVICES else "check"))
    for m in JS_ENV.finditer(text):
        envs.setdefault(m.group(1), []).append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")


# ------------------------------------------------------------------ CI / OIDC
def _guess_repo(root: Path) -> Optional[str]:
    try:
        url = subprocess.run(["git", "-C", str(root), "config", "--get", "remote.origin.url"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def _scan_ci(root: Path, findings: list) -> dict:
    ci = {"github": False, "gitlab": False}
    for p in _walk(root):
        rel = str(p.relative_to(root))
        if rel.startswith(".github/workflows/") and p.suffix in (".yml", ".yaml"):
            text = _read(p)
            if "role-to-assume" in text:
                ci["github"] = True
                if not re.search(r"id-token:\s*write", text):
                    findings.append(Finding(
                        "OIDC_MISSING_ID_TOKEN_PERMISSION", "critical",
                        f"{rel} assumes an AWS role via OIDC but never grants `id-token: write`. "
                        "The job cannot request a token, so the role assumption fails with a "
                        "misleading credentials error.",
                        [rel], "Add `permissions:\\n  id-token: write\\n  contents: read` to the workflow or job."))
        elif rel == ".gitlab-ci.yml":
            text = _read(p)
            if re.search(r"^\s*id_tokens:", text, re.M):
                ci["gitlab"] = True
    return ci


# ------------------------------------------------------------------ packages
def _python_deps(root: Path) -> Optional[set[str]]:
    deps: set[str] = set()
    found = False
    norm = lambda s: re.split(r"[<>=!~\[; ]", s.strip(), maxsplit=1)[0].lower().replace("_", "-")
    for p in _walk(root):
        if re.fullmatch(r"requirements[\w.\-]*\.txt", p.name):
            found = True
            deps |= {norm(l) for l in _read(p).splitlines() if l.strip() and not l.lstrip().startswith(("#", "-"))}
        elif p.name == "pyproject.toml":
            found = True
            try:
                data = tomllib.loads(_read(p)).get("project", {})
            except tomllib.TOMLDecodeError:
                continue
            for d in data.get("dependencies", []):
                deps.add(norm(d))
            for group in data.get("optional-dependencies", {}).values():
                deps |= {norm(d) for d in group}
    return deps if found else None


def _js_deps(root: Path) -> Optional[set[str]]:
    pj = root / "package.json"
    if not pj.exists():
        return None
    try:
        data = json.loads(_read(pj))
    except ValueError:
        return set()
    return set(data.get("dependencies", {})) | set(data.get("devDependencies", {}))


# ------------------------------------------------------------------ terraform generation
SCOPES = {  # service -> (variable, description)
    "s3": ("s3_bucket_arn", "ARN of the S3 bucket the app uses."),
    "dynamodb": ("dynamodb_table_arn", "ARN of the DynamoDB table the app uses."),
    "sqs": ("sqs_queue_arn", "ARN of the SQS queue the app uses."),
    "sns": ("sns_topic_arn", "ARN of the SNS topic the app uses."),
    "secretsmanager": ("secret_arn", "ARN of the Secrets Manager secret the app reads."),
    "lambda": ("lambda_function_arn", "ARN of the Lambda function the app invokes."),
    "kms": ("kms_key_arn", "ARN of the KMS key the app uses."),
    "ssm": ("ssm_parameter_arn", "ARN of the SSM parameter the app reads."),
}


def _scope(u: Usage):
    var, desc = SCOPES.get(u.service, (u.service.replace("-", "_") + "_resource_arn",
                                       f"ARN of the {u.service} resource the app uses."))
    if u.service == "s3" and u.action != "ListBucket":
        return "S3Object", f'"${{var.{var}}}/*"', var, desc
    return (u.service.replace("-", " ").title().replace(" ", "") + ("Bucket" if u.service == "s3" else ""),
            f"var.{var}", var, desc)


def _hcl_var(name: str, desc: str, extra: str = "") -> str:
    return f'variable "{name}" {{\n  description = "{desc}"\n  type        = string\n{extra}}}\n'


def _gen_iam(usages: list[Usage]) -> dict[str, str]:
    groups: dict[tuple, set] = {}
    vars_: dict[str, str] = {}
    for u in usages:
        sid, res, var, desc = _scope(u)
        groups.setdefault((sid, res), set()).add(u.iam)
        vars_[var] = desc
    stmts = ""
    for (sid, res), actions in sorted(groups.items()):
        acts = ", ".join(f'"{a}"' for a in sorted(actions))
        stmts += f'  statement {{\n    sid       = "{sid}"\n    actions   = [{acts}]\n    resources = [{res}]\n  }}\n\n'
    iam = (
        "# Generated by InfraSec from the SDK calls in this repo. REVIEW before applying:\n"
        "# IAM changes always need a human. Resources are variables on purpose (no wildcards).\n\n"
        'data "aws_iam_policy_document" "app" {\n' + stmts.rstrip("\n") + "\n}\n\n"
        'resource "aws_iam_role" "app" {\n  name = "${var.name_prefix}-app"\n\n'
        '  assume_role_policy = jsonencode({\n    Version = "2012-10-17"\n    Statement = [{\n'
        '      Effect    = "Allow"\n      Principal = { Service = var.app_service_principal }\n'
        '      Action    = "sts:AssumeRole"\n    }]\n  })\n}\n\n'
        'resource "aws_iam_role_policy" "app" {\n  name   = "least-privilege"\n  role   = aws_iam_role.app.id\n'
        "  policy = data.aws_iam_policy_document.app.json\n}\n"
    )
    variables = (
        _hcl_var("name_prefix", "Prefix for created resource names.")
        + "\n" + _hcl_var("app_service_principal", "Service that runs the app (lambda.amazonaws.com, ecs-tasks.amazonaws.com, ...).",
                          '  default     = "lambda.amazonaws.com"\n')
    )
    for name, desc in sorted(vars_.items()):
        variables += "\n" + _hcl_var(name, desc)
    return {"iam.tf": iam, "variables.tf": variables}


def _gen_oidc(ci: dict, repo: Optional[str]) -> str:
    slug = repo or "ORG/REPO"
    out = ("# CI deploy role, pinned to ONE repo and branch. Fixes the common OIDC trial-and-error:\n"
           "# wrong/missing `sub`, wildcard trust, and over-broad roles.\n"
           "# Attach only the permissions your deploy actually needs (never AdministratorAccess).\n\n")
    if ci["github"]:
        out += (
            'data "aws_iam_openid_connect_provider" "github" {\n  url = "https://token.actions.githubusercontent.com"\n}\n\n'
            'resource "aws_iam_role" "ci_deploy" {\n  name = "${var.name_prefix}-ci-deploy"\n\n'
            '  assume_role_policy = jsonencode({\n    Version = "2012-10-17"\n    Statement = [{\n'
            '      Effect    = "Allow"\n      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }\n'
            '      Action    = "sts:AssumeRoleWithWebIdentity"\n      Condition = {\n        StringEquals = {\n'
            '          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"\n'
            f'          "token.actions.githubusercontent.com:sub" = "repo:{slug}:ref:refs/heads/main"\n'
            "        }\n      }\n    }]\n  })\n}\n")
    if ci["gitlab"]:
        out += (
            '\ndata "aws_iam_openid_connect_provider" "gitlab" {\n  url = "https://gitlab.com"\n}\n\n'
            'resource "aws_iam_role" "ci_deploy_gitlab" {\n  name = "${var.name_prefix}-ci-deploy-gitlab"\n\n'
            '  assume_role_policy = jsonencode({\n    Version = "2012-10-17"\n    Statement = [{\n'
            '      Effect    = "Allow"\n      Principal = { Federated = data.aws_iam_openid_connect_provider.gitlab.arn }\n'
            '      Action    = "sts:AssumeRoleWithWebIdentity"\n      Condition = {\n        StringEquals = {\n'
            '          "gitlab.com:aud" = "sts.amazonaws.com"\n'
            f'          "gitlab.com:sub" = "project_path:{slug}:ref_type:branch:ref:main"\n'
            "        }\n      }\n    }]\n  })\n}\n")
    return out


def _gen_env(envs: dict[str, list[str]]) -> str:
    plain = sorted(n for n in envs if not AMBIENT_ENV.match(n) and not SECRET_NAME.search(n))
    secret = sorted(n for n in envs if not AMBIENT_ENV.match(n) and SECRET_NAME.search(n))
    body = "# Environment the application reads. Secrets are referenced by ARN, never plain env vars.\n\n"
    body += 'variable "app_env" {\n  description = "Non-secret environment variables."\n  type        = map(string)\n  default = {\n'
    body += "".join(f'    {n} = ""\n' for n in plain) + "  }\n}\n"
    if secret:
        body += '\nvariable "app_secret_arns" {\n  description = "Secrets Manager ARNs for secret-looking variables."\n  type        = map(string)\n  default = {\n'
        body += "".join(f'    {n} = ""\n' for n in secret) + "  }\n}\n"
    return body


# ------------------------------------------------------------------ entry point
def suggest(root: str | Path, repo: Optional[str] = None) -> Suggestion:
    root = Path(root)
    s = Suggestion(repo=repo or _guess_repo(root))
    for p in _walk(root):
        rel = str(p.relative_to(root))
        if p.suffix == ".py":
            _scan_python(p, rel, s.usages, s.env_vars)
        elif p.suffix in (".js", ".mjs", ".ts", ".tsx"):
            _scan_js(p, rel, s.usages, s.env_vars)

    ci = _scan_ci(root, s.findings)

    # packages
    py_uses = {u.file for u in s.usages if u.file.endswith(".py")}
    if py_uses:
        deps = _python_deps(root)
        if deps is None or "boto3" not in deps:
            s.findings.append(Finding(
                "PACKAGE_MISSING", "warn",
                "Code calls AWS through boto3 but boto3 is not declared in requirements/pyproject."
                if deps is not None else "Code calls AWS through boto3 but no requirements.txt or pyproject.toml exists.",
                sorted(py_uses)[:5], "Add `boto3` (pinned, e.g. boto3==1.35.*) to requirements.txt."))
    js_uses = {u.file for u in s.usages if not u.file.endswith(".py")}
    if js_uses:
        jd = _js_deps(root)
        for svc in sorted({u.service for u in s.usages if not u.file.endswith(".py")}):
            if jd is None or f"@aws-sdk/client-{svc}" not in jd:
                s.findings.append(Finding("PACKAGE_MISSING", "warn",
                                          f"Code imports @aws-sdk/client-{svc} but package.json does not declare it.",
                                          sorted(js_uses)[:5], f"npm install @aws-sdk/client-{svc}"))

    # env / secrets
    for name, ev in sorted(s.env_vars.items()):
        if SECRET_NAME.search(name) and not AMBIENT_ENV.match(name):
            s.findings.append(Finding(
                "SECRET_IN_ENV", "warn",
                f"`{name}` looks like a secret and is read from an environment variable.", ev[:3],
                "Store it in Secrets Manager or SSM SecureString and inject it at runtime by ARN; don't put it in Terraform or plain env."))

    # IAM
    if s.usages:
        s.files.update(_gen_iam(s.usages))
        actions = {u.iam for u in s.usages}
        s.findings.append(Finding(
            "IAM_LEAST_PRIVILEGE", "info",
            f"Derived {len(actions)} IAM action(s) from SDK calls: {', '.join(sorted(actions))}.",
            [f"{u.file}:{u.line}" for u in s.usages[:5]],
            "Review suggested-infra/iam.tf and set the resource ARN variables."))
        if any(u.confidence == "check" for u in s.usages):
            s.findings.append(Finding(
                "IAM_ACTION_UNVERIFIED", "warn",
                "Some actions were derived from method names and are not on the verified list: " +
                ", ".join(sorted({u.iam for u in s.usages if u.confidence == 'check'})) + ".",
                [], "Check each against the AWS service authorization reference."))

    # OIDC
    if ci["github"] or ci["gitlab"]:
        s.files["oidc.tf"] = _gen_oidc(ci, s.repo)
        if not s.repo:
            s.findings.append(Finding("REPO_UNKNOWN", "warn",
                                      "Could not determine ORG/REPO, so the OIDC trust uses the placeholder ORG/REPO.",
                                      [], "Re-run with --repo ORG/REPO."))
        s.files.setdefault("variables.tf", _hcl_var("name_prefix", "Prefix for created resource names."))
    if any(n for n in s.env_vars if not AMBIENT_ENV.match(n)):
        s.files["app_env.tf"] = _gen_env(s.env_vars)
    return s


def to_markdown(s: Suggestion) -> str:
    lines = ["## InfraSec suggestions", ""]
    if not s.findings and not s.files:
        return "## InfraSec suggestions\n\nNo infrastructure needs detected in this repo.\n"
    lines += ["| Severity | Code | Finding | Evidence | Fix |", "|---|---|---|---|---|"]
    for f in sorted(s.findings, key=lambda f: {"critical": 0, "warn": 1, "info": 2}[f.severity]):
        lines.append(f"| {f.severity} | `{f.code}` | {f.message} | {', '.join(f.evidence)} | {f.fix} |")
    if s.files:
        lines += ["", "Generated files (in `suggested-infra/`): " + ", ".join(f"`{n}`" for n in sorted(s.files)),
                  "", "IAM and trust changes always need human review before they are applied."]
    return "\n".join(lines) + "\n"
