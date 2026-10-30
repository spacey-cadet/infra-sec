#!/usr/bin/env python3
"""Nemotron proposes a Terraform fix; the deterministic gate must agree before it is kept.

Flow (only for a held change whose findings are ALL auto-fixable):
  1. Ask an NVIDIA Nemotron model (OpenAI-compatible endpoint, Nebius by default) for the corrected .tf file.
  2. Guardrails: .tf file only, small diff, same set of resources.
  3. Write the file, regenerate the plan, re-run the deterministic evaluator.
  4. Gate says auto_apply -> keep (and commit with --commit). Otherwise revert.

The model never decides. A bad, unsafe or unusable proposal is simply discarded.
Never fails the pipeline: exits 0 in every case and prints what happened.

Environment:
  NEBIUS_API_KEY, NEBIUS_MODEL_ID, optional NEBIUS_BASE_URL
  INFRASEC_RECHECK_CMD   optional shell command that regenerates the plan and runs the
                         gate (exit 0 = auto_apply). Default: terraform fmt/init/plan/show,
                         then scripts/infrasec_decide.py.
  INFRASEC_TOKEN, CI_API_V4_URL, CI_PROJECT_ID, CI_COMMIT_REF_NAME   post an MR note (optional)

Usage:
  infrasec_fix.py --decision infrasec-decision.json --tf demo-target/main.tf [--commit]
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import infrasec_explain as ex  # noqa: E402
from agent.fix_hints import AUTO_FIXABLE, FIX_HINTS  # noqa: E402
from infrasec_decide import MAX_AUTOFIX_ATTEMPTS  # noqa: E402

MAX_CHANGED_LINES = 10
MAX_FILE_CHARS = 20000
TAG = "[infrasec-autofix]"

SYSTEM_PROMPT = (
    "You fix Terraform security findings. A deterministic evaluator has ALREADY decided the "
    "change must be held; you must not argue with it. Return ONLY the complete corrected "
    "contents of the file: no prose, no explanation, no code fences. Change as little as "
    "possible, fix only the listed findings, and never add, remove or rename resources. "
    "If a previous version of the file is provided, restore the exact previous value for "
    "the loosened setting instead of guessing a new one."
)


def build_messages(decision: dict, tf_path: str, current: str, base: str | None) -> list[dict]:
    findings = []
    for f in decision.get("risk_flags", []):
        findings.append(f"- {f['code']}: {f['message']}\n  Hint: {FIX_HINTS.get(f['code'], '')}")
    user = "Findings to fix:\n" + "\n".join(findings) + f"\n\nCurrent file {tf_path}:\n{current}"
    if base:
        user += f"\n\nPrevious version of the file on the target branch:\n{base}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def extract_file(text: str) -> str:
    text = ex.strip_reasoning(text)
    m = re.search(r"```(?:hcl|terraform|tf)?\n(.*?)```", text, flags=re.DOTALL)
    if m:
        text = m.group(1)
    return text.strip("\n") + "\n"


def resource_set(text: str) -> set[tuple[str, str]]:
    return set(re.findall(r'^\s*resource\s+"([^"]+)"\s+"([^"]+)"', text, flags=re.M))


def changed_lines(a: str, b: str) -> int:
    diff = difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
    return sum(1 for ln in diff if ln[:1] in "+-" and not ln.startswith(("+++", "---")))


def propose(base_url: str, api_key: str, model: str, messages: list[dict]) -> str | None:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": 4000}
    try:
        data = ex._request(url, headers, body, timeout=90)
        return extract_file(data["choices"][0]["message"]["content"] or "")
    except (urllib.error.URLError, KeyError, ValueError, OSError) as exc:
        print(f"Model call failed: {type(exc).__name__}: {exc}")
        return None


def base_version(path: Path, ref: str) -> str | None:
    try:
        out = subprocess.run(["git", "show", f"{ref}:{path.as_posix()}"], capture_output=True,
                             text=True, timeout=30)
        return out.stdout if out.returncode == 0 and out.stdout else None
    except Exception:
        return None


def gate_passes(tf: Path, attempt: int) -> bool:
    """Regenerate the plan from the patched file and re-run the deterministic gate."""
    override = os.environ.get("INFRASEC_RECHECK_CMD")
    if override:
        return subprocess.run(override, shell=True).returncode == 0
    with tempfile.TemporaryDirectory() as out:
        plan = f"{out}/plan.fixed.json"
        d, f = shlex.quote(str(tf.parent)), shlex.quote(tf.name)
        steps = (f"cd {d} && terraform fmt {f} >/dev/null && "
                 "terraform init -input=false -backend=false >/dev/null && "
                 f"terraform plan -input=false -out=tfplan.fixed >/dev/null && "
                 f"terraform show -json tfplan.fixed > {shlex.quote(plan)}; rc=$?; rm -f tfplan.fixed; exit $rc")
        if subprocess.run(steps, shell=True).returncode != 0:
            print("Could not regenerate the plan from the proposed file.")
            return False
        rc = subprocess.run([sys.executable, str(HERE / "infrasec_decide.py"), "--plan", plan,
                             "--ci-status", "pass", "--attempt", str(attempt), "--out-dir", out],
                            capture_output=True, text=True).returncode
        return rc == 0


def commit(tf: Path) -> None:
    cfg = ["-c", "user.name=infrasec-bot", "-c", "user.email=infrasec-bot@users.noreply.gitlab.com"]
    subprocess.run(["git", "add", str(tf)], check=True)
    subprocess.run(["git", *cfg, "commit", "-m",
                    f"infrasec: Nemotron-proposed fix, verified by the gate {TAG}"], check=True)


def note(body: str) -> None:
    text = (f"**Fix proposed by NVIDIA Nemotron on {ex.provider_label()}** "
            "(the deterministic gate re-checks every proposal)\n\n" + body)
    print(text)
    try:
        ex.post_note(text)
    except (urllib.error.URLError, KeyError, ValueError, OSError) as exc:
        print(f"Could not post the MR note: {exc}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision", required=True)
    ap.add_argument("--tf", required=True, help="the .tf file to fix")
    ap.add_argument("--base-ref", default=f"origin/{os.environ.get('CI_DEFAULT_BRANCH', 'main')}")
    ap.add_argument("--commit", action="store_true", help="git commit the verified fix")
    args = ap.parse_args(argv)

    api_key, model = os.environ.get("NEBIUS_API_KEY"), os.environ.get("NEBIUS_MODEL_ID")
    base_url = os.environ.get("NEBIUS_BASE_URL", ex.DEFAULT_BASE_URL)
    if not (api_key and model):
        print("NEBIUS_API_KEY or NEBIUS_MODEL_ID not set; skipping the fix.")
        return 0
    if not os.path.exists(args.decision):
        print("Decision file not found; skipping the fix.")
        return 0
    decision = json.loads(Path(args.decision).read_text(encoding="utf-8"))
    if decision.get("action") != "hold":
        print("Gate did not hold this change; nothing to fix.")
        return 0

    codes = [f["code"] for f in decision.get("risk_flags", [])]
    blockers = [c for c in codes if c not in AUTO_FIXABLE]
    if not codes or blockers:
        note("Not attempted: " + (", ".join(f"`{c}`" for c in blockers) or "no findings")
             + " need a human reviewer. Nemotron only proposes fixes for pure tightenings.")
        return 0
    attempt = int(decision.get("attempt", 0))
    if attempt >= MAX_AUTOFIX_ATTEMPTS:
        note(f"Not attempted: the auto-fix budget ({MAX_AUTOFIX_ATTEMPTS}) is used up. Escalated to a human.")
        return 0

    tf = Path(args.tf)
    if tf.suffix != ".tf" or not tf.is_file():
        print(f"Refusing: {args.tf} is not an existing .tf file.")
        return 0
    original = tf.read_text(encoding="utf-8")
    if len(original) > MAX_FILE_CHARS:
        print("Refusing: file too large for a safe proposal.")
        return 0

    fixed = propose(base_url, api_key, model,
                    build_messages(decision, args.tf, original, base_version(tf, args.base_ref)))
    if fixed is None:
        return 0
    if fixed == original:
        note("Rejected: the proposal changed nothing.")
        return 0
    if resource_set(fixed) != resource_set(original):
        note("Rejected: the proposal added, removed or renamed a resource.")
        return 0
    n = changed_lines(original, fixed)
    if n > MAX_CHANGED_LINES:
        note(f"Rejected: the proposal changed {n} lines (limit {MAX_CHANGED_LINES}).")
        return 0

    tf.write_text(fixed, encoding="utf-8")
    if not gate_passes(tf, attempt):
        tf.write_text(original, encoding="utf-8")
        note("Rejected: the deterministic gate still holds the patched file, so nothing was changed. "
             "A human needs to fix this one.")
        return 0

    if args.commit:
        commit(tf)
    note(f"Kept: the gate returns `auto_apply` on the patched file ({n} lines changed in `{args.tf}`)."
         + (" Committed." if args.commit else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
