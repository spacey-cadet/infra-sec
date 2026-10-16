from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _signed_post(url: str, payload: dict) -> dict:
    """POST JSON to an AWS_IAM Lambda Function URL using the ambient AWS role."""
    try:
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        import boto3
    except ImportError as exc:  # pragma: no cover - install boto3 extra
        raise RuntimeError("Install infra-risk with its aws extra (pip install 'infra-risk[aws]').") from exc

    session = boto3.Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials found. Configure the CI OIDC role first.")
    frozen = credentials.get_frozen_credentials()
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    body = json.dumps(payload).encode("utf-8")
    request = AWSRequest(method="POST", url=url, data=body, headers={"content-type": "application/json"})
    SigV4Auth(frozen, "lambda", region).add_auth(request)
    req = urllib.request.Request(url, data=body, headers=dict(request.headers), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Decision API returned HTTP {exc.code}: {detail}") from exc


def _model_advisory(plan_json: str) -> dict | None:
    model_id = os.environ.get("INFRA_RISK_GLINER_MODEL", "")
    if not model_id:
        return None
    try:
        from gliner2 import AutoExtractor
    except ImportError as exc:  # pragma: no cover - optional extra
        raise RuntimeError("GLiNER enabled but missing. Install 'infra-risk[gliner]'.") from exc

    # Keep model scope deliberately narrow: classify the human-readable plan
    # metadata, while deterministic checks remain the only source of action.
    model = AutoExtractor.from_pretrained(model_id)
    try:
        plan = json.loads(plan_json)
        changes = []
        for item in plan.get("resource_changes", []):
            change = item.get("change", {})
            changes.append(
                f"{item.get('address', '?')} ({item.get('type', '?')}): "
                f"{','.join(change.get('actions', []))}"
            )
        summary = "Terraform plan changes:\n" + "\n".join(changes[:100])
        if not changes:
            summary += "No resource changes were listed."
    except (ValueError, AttributeError):
        summary = "Terraform plan JSON could not be summarized."
    labels = {
        "security_sensitive": "Changes to IAM, identity, access, network security, or secrets",
        "cost_increasing": "Changes likely to increase cloud infrastructure cost",
        "routine_change": "Routine low-risk infrastructure maintenance",
        "uncertain": "Insufficient information to classify the infrastructure change",
    }
    return {"model": model_id, "labels": model.classify_text(summary, {"plan_risk": labels})}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Submit a Terraform plan to Infra Risk")
    parser.add_argument("--plan", default="plan.json", help="terraform show -json output")
    parser.add_argument("--api-url", default=os.environ.get("INFRA_RISK_API_URL"))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "local/unknown"))
    parser.add_argument("--pr", default=os.environ.get("PR_NUMBER", "0"))
    parser.add_argument("--sha", default=os.environ.get("HEAD_SHA", os.environ.get("GITHUB_SHA", "")))
    parser.add_argument("--baseline-usd", type=float, default=float(os.environ.get("BASELINE_USD", "5")))
    args = parser.parse_args(argv)
    if not args.api_url:
        parser.error("--api-url or INFRA_RISK_API_URL is required")

    with open(args.plan, encoding="utf-8") as stream:
        plan_json = stream.read()
    payload = {
        "repo": args.repo,
        "pr_number": str(args.pr),
        "head_sha": args.sha,
        "plan_id": args.sha or "local-plan",
        "baseline_usd": args.baseline_usd,
        "plan_json": plan_json,
    }
    advisory = _model_advisory(plan_json)
    if advisory:
        payload["model_advisory"] = advisory
    decision = _signed_post(args.api_url, payload)
    print(json.dumps(decision, indent=2))
    return 0 if decision.get("action") == "auto_apply" else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
