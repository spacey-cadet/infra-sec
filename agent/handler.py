"""Lambda entry point.

Triggered by an SQS message containing {repo, pr_number, head_sha,
plan_json_s3_uri (or inline plan_json), baseline_usd}, pushed by the
GitHub Actions workflow after `terraform show -json tfplan.binary > plan.json`.

Any unhandled exception anywhere in this function results in a "hold"
decision and notification, never a silent auto-apply. That's the single
most important property of this handler, and it's enforced by wrapping
the whole body in try/except at the outermost layer.
"""
from __future__ import annotations
import json
import os
import traceback

import boto3

from .plan_parser import ParsedPlan
from .cost_estimate import CostEstimateResult
from .decision_engine import evaluate, Decision, RiskFlag
from .dynamo_store import put_decision, get_known_resource_types, DecisionRecord, now_iso
from .notify import notify
from .github_client import post_check_run, post_pr_comment
from .strands_agent import run_guardian_review

APPLY_ROLE_ARN = os.environ.get("GUARDIAN_APPLY_ROLE_ARN", "")


def _fetch_plan_json(event_body: dict) -> str:
    """Plan JSON can arrive inline (small plans) or as an S3 pointer
    (larger plans, to stay under SQS's 256KB message size limit)."""
    if "plan_json" in event_body:
        return event_body["plan_json"]
    if "plan_json_s3_uri" in event_body:
        uri = event_body["plan_json_s3_uri"]
        assert uri.startswith("s3://"), f"unexpected plan_json_s3_uri: {uri}"
        _, _, rest = uri.partition("s3://")
        bucket, _, key = rest.partition("/")
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read().decode()
    raise ValueError("event body missing both 'plan_json' and 'plan_json_s3_uri'")


def _trigger_apply(repo: str, pr_number: str) -> None:
    """Invokes terraform apply via a separate, least-privilege OIDC apply
    role (see terraform/oidc.tf). In this reference implementation, this
    triggers a downstream CI job, for example by updating a GitHub
    deployment status or re-dispatching a workflow, rather than running
    `terraform apply` directly inside this Lambda. That way the actual
    apply always runs under GitHub Actions' OIDC-federated credentials,
    not the Lambda's."""
    print(f"[handler] auto-apply approved for {repo} PR #{pr_number}; "
          f"signalling CI to proceed using apply role {APPLY_ROLE_ARN or '(unset)'}")
    # In a full deployment this would call the GitHub API to set a
    # deployment status / dispatch a workflow_dispatch event that runs
    # `terraform apply` under the scoped apply role. Left as an explicit
    # integration point rather than hidden behind a fake success return.


def _process(event_body: dict) -> dict:
    repo = event_body.get("repo", "<unknown-repo>")
    pr_number = str(event_body.get("pr_number", "0"))
    head_sha = event_body.get("head_sha", "")
    plan_id = event_body.get("plan_id") or head_sha or "unknown-plan"
    baseline_usd = float(event_body.get("baseline_usd", 5.0))

    known_types = get_known_resource_types(repo)
    try:
        raw_plan_json = _fetch_plan_json(event_body)
        review = run_guardian_review(raw_plan_json, baseline_usd, known_types)
        parsed = review.parsed_plan
        decision = review.decision
    except Exception as e:  # noqa: BLE001 (deliberate catch-all, fail closed)
        parsed = ParsedPlan(parse_ok=False, parse_error=f"unhandled fetch/review error: {e}")
        decision = evaluate(
            parsed,
            CostEstimateResult(delta_usd=0.0, baseline_usd=baseline_usd, pct_of_baseline=0.0, method="n/a"),
            known_types,
        )

    record = DecisionRecord(
        repo=repo,
        plan_id=plan_id,
        timestamp=now_iso(),
        decision=decision.action,
        risk_flags=[f.__dict__ for f in decision.risk_flags],
        cost_delta_usd=decision.cost_delta_usd,
        confidence=decision.confidence,
        oidc_diff=decision.to_dict()["oidc_diff"],
        resource_types_seen=list(parsed.new_resource_types) if parsed.parse_ok else [],
    )
    try:
        put_decision(record)
    except Exception as e:  # noqa: BLE001
        print(f"[handler] WARNING: failed to write decision log: {e}")

    try:
        post_check_run(repo, head_sha, decision)
        post_pr_comment(repo, pr_number, decision)
    except Exception as e:  # noqa: BLE001
        print(f"[handler] WARNING: failed to post GitHub feedback: {e}")

    if decision.action == "hold":
        try:
            notify(repo, pr_number, decision)
        except Exception as e:  # noqa: BLE001
            print(f"[handler] ERROR: failed to send hold notification: {e}")
            # Even if the notification itself fails, we must not fall through
            # to auto-apply. Re-raise so the Lambda invocation is marked
            # failed and the CI job stays blocked rather than silently
            # proceeding.
            raise
    else:
        _trigger_apply(repo, pr_number)

    return decision.to_dict()


def lambda_handler(event, context):
    """
    SQS-triggered handler. Each SQS record's body is a JSON string matching
    the shape described in _fetch_plan_json / _process.
    """
    results = []
    for record in event.get("Records", [{"body": json.dumps(event)}]):
        try:
            body = json.loads(record["body"]) if isinstance(record.get("body"), str) else record.get("body", {})
            results.append(_process(body))
        except Exception as e:  # noqa: BLE001 (outermost fail-closed net)
            print("[handler] UNHANDLED EXCEPTION, failing closed:\n" + traceback.format_exc())
            fail_closed = Decision(
                action="hold",
                reasoning=f"Unhandled exception in guardian handler: {e}. Failing closed by design.",
                risk_flags=[RiskFlag("HANDLER_EXCEPTION", str(e), "critical")],
            )
            try:
                repo = json.loads(record.get("body", "{}")).get("repo", "<unknown>") if isinstance(record.get("body"), str) else "<unknown>"
                notify(repo, "unknown", fail_closed)
            except Exception:
                print("[handler] also failed to notify on the fail-closed path; a human needs to check CloudWatch logs.")
            results.append(fail_closed.to_dict())

    return {"statusCode": 200, "body": json.dumps(results)}
