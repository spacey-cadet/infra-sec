"""github_api

Posts the decision as a GitHub Check Run and/or PR comment, so reviewers
see it directly in the PR instead of only in Slack. Uses a fine-grained
GitHub App token or PAT stored in Secrets Manager or env, injected into
the Lambda's environment at deploy time.
"""
from __future__ import annotations
import json
import os
from typing import Optional

import urllib.request
import urllib.error

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN = os.environ.get("GUARDIAN_GITHUB_TOKEN", "")


def _request(method: str, path: str, body: Optional[dict] = None) -> dict:
    url = f"{GITHUB_API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": True, "status": e.code, "body": e.read().decode()}


def post_check_run(repo: str, head_sha: str, decision) -> dict:
    """Creates (or would update, in a fuller implementation with a stored
    check_run_id) a GitHub Check Run reflecting the guardian's verdict, so
    the PR's required-checks list blocks merge on a 'hold'."""
    conclusion = "success" if decision.action == "auto_apply" else "action_required"
    title = (
        "OIDC trust policy widened, held for review"
        if decision.highest_priority
        else ("Held for human review" if decision.action == "hold" else "Auto-applied")
    )
    summary_lines = [f"**Decision:** `{decision.action}`", f"**Confidence:** {decision.confidence:.2f}", ""]
    for flag in decision.risk_flags:
        summary_lines.append(f"- `{flag.severity}` **{flag.code}**: {flag.message}")
    if not decision.risk_flags:
        summary_lines.append("- No risk flags raised.")

    body = {
        "name": "Infra Cost Guardian",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": title,
            "summary": "\n".join(summary_lines),
        },
    }
    if not GITHUB_TOKEN:
        print(f"[github_client] GUARDIAN_GITHUB_TOKEN not set, would POST check run:\n{json.dumps(body, indent=2)}")
        return {"skipped": True}
    return _request("POST", f"/repos/{repo}/check-runs", body)


def post_pr_comment(repo: str, pr_number: str, decision) -> dict:
    body_text = f"**Infra Cost Guardian verdict: `{decision.action}`**\n\n{decision.reasoning}\n\n"
    for flag in decision.risk_flags:
        body_text += f"- `{flag.severity}` {flag.message}\n"
    body_text += f"\nEstimated cost delta: ${decision.cost_delta_usd:.2f}/mo"

    payload = {"body": body_text}
    if not GITHUB_TOKEN:
        print(f"[github_client] GUARDIAN_GITHUB_TOKEN not set, would POST PR comment:\n{body_text}")
        return {"skipped": True}
    return _request("POST", f"/repos/{repo}/issues/{pr_number}/comments", payload)
