#!/usr/bin/env python3
"""Local demo runner for Infra Cost Guardian.

This script runs the same Strands-backed review path used by Lambda, but
against a local Terraform plan JSON fixture. It is meant for repeatable demo
recordings where live AWS/GitHub wiring would add noise.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from agent.strands_agent import run_guardian_review


DEFAULT_KNOWN_TYPES = {
    "aws_lambda_function",
    "aws_iam_role",
    "aws_nat_gateway",
}


def _print_header(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def _print_plan_summary(review) -> None:
    parsed = review.parsed_plan
    print(f"Parse status: {'ok' if parsed.parse_ok else 'failed'}")
    if parsed.parse_error:
        print(f"Parse error: {parsed.parse_error}")

    print(f"Resource changes: {len(parsed.resource_changes)}")
    for rc in parsed.resource_changes:
        actions = "/".join(rc.actions) or "none"
        markers = []
        if rc.is_iam_related:
            markers.append("IAM")
        if rc.has_trust_policy:
            markers.append("trust-policy")
        if rc.is_replace:
            markers.append("replace")
        suffix = f" [{' / '.join(markers)}]" if markers else ""
        print(f"  - {rc.address} ({rc.type}) actions={actions}{suffix}")


def _print_decision_details(review) -> None:
    decision = review.decision
    print(f"Decision: {decision.action}")
    print(f"Reason: {decision.reasoning}")
    print(f"Confidence: {decision.confidence:.2f}")
    print(f"Cost impact: {'+' if decision.cost_delta_usd >= 0 else ''}${decision.cost_delta_usd:.2f}/mo")
    print(f"Highest priority: {'yes' if decision.highest_priority else 'no'}")

    if decision.risk_flags:
        print("Risk flags:")
        for flag in decision.risk_flags:
            print(f"  - {flag.severity.upper()} {flag.code}: {flag.message}")
    else:
        print("Risk flags: none")

    if decision.oidc_diff and decision.oidc_diff.changed:
        diff = decision.oidc_diff
        before = diff.before.patterns if diff.before else []
        after = diff.after.patterns if diff.after else []
        print("OIDC trust diff:")
        print(f"  key: {diff.key}")
        print(f"  before: {', '.join(before) or '(none)'}")
        print(f"  after: {', '.join(after) or '(none)'}")
        print(f"  widened: {'yes' if diff.widened else 'no'}")
        if diff.examples_newly_allowed:
            print("  newly allowed examples:")
            for example in diff.examples_newly_allowed:
                print(f"    - {example}")


def _format_notification_preview(repo: str, pr_number: str, decision) -> str:
    status = "HELD" if decision.action == "hold" else "auto-applied"
    lines = [f"Terraform plan {status} -- {repo}, PR #{pr_number}"]

    if decision.oidc_diff and decision.oidc_diff.changed:
        diff = decision.oidc_diff
        short_key = "sub" if "sub" in (diff.key or "") else "aud"
        before = diff.before.patterns if diff.before else []
        after = diff.after.patterns if diff.after else []
        lines.append(f"Risk: OIDC trust policy {'widened' if diff.widened else 'changed'}")
        lines.append(f"  {short_key}: {', '.join(before) or '(none)'} -> {', '.join(after) or '(none)'}")
        if diff.examples_newly_allowed:
            lines.append("This would newly allow, e.g.: " + "; ".join(diff.examples_newly_allowed))
    elif decision.risk_flags:
        severity_rank = {"critical": 0, "warn": 1, "info": 2}
        top = sorted(decision.risk_flags, key=lambda f: severity_rank[f.severity])[0]
        lines.append(f"Risk: {top.message}")
    else:
        lines.append("No IAM/security resources touched.")

    lines.append(f"Cost impact: {'+' if decision.cost_delta_usd >= 0 else ''}${decision.cost_delta_usd:.2f}/mo (est.)")
    if decision.action == "hold":
        lines.append("[Approve & Apply]  [View full plan]  [Reject]")
    return "\n".join(lines)


def run_demo(plan_path: Path, baseline_usd: float, known_resource_types: set[str], repo: str, pr_number: str) -> int:
    plan_json = plan_path.read_text()
    review = run_guardian_review(plan_json, baseline_usd, known_resource_types)

    _print_header("Infra Cost Guardian Local Demo")
    print(f"Plan file: {plan_path}")
    print(f"Repo / PR: {repo} #{pr_number}")
    print("Strands tool path: " + " -> ".join(review.tool_trace))

    _print_header("Plan Summary")
    _print_plan_summary(review)

    _print_header("Guardian Decision")
    _print_decision_details(review)

    _print_header("Notification Preview")
    print(_format_notification_preview(repo, pr_number, review.decision))

    return 0 if review.decision.action == "auto_apply" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Infra Cost Guardian against a local Terraform plan JSON file.")
    parser.add_argument("plan_json", type=Path, help="Path to terraform show -json output or a fixture JSON file.")
    parser.add_argument("--baseline-usd", type=float, default=5.0, help="Current monthly baseline for cost thresholding.")
    parser.add_argument(
        "--known-resource-type",
        action="append",
        default=None,
        help="Resource type already seen in this repo. Can be passed multiple times.",
    )
    parser.add_argument("--repo", default="you/repo", help="Repo label to show in notification preview.")
    parser.add_argument("--pr-number", default="12", help="PR number to show in notification preview.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    known_types = set(args.known_resource_type) if args.known_resource_type else set(DEFAULT_KNOWN_TYPES)
    return run_demo(args.plan_json, args.baseline_usd, known_types, args.repo, args.pr_number)


if __name__ == "__main__":
    raise SystemExit(main())
