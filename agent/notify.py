"""sns_notify

The single escalation channel out of this agent. When the decision engine
returns "hold," this is the only path that surfaces it to a human. It's
kept singular on purpose, so there's exactly one place to audit for
whether the notification actually went out.

The message format follows the spec: a one-line decision ask, the specific
risk, a plain-English consequence sentence, and action buttons if the
downstream Slack/chat integration supports them (SNS to Slack via a
subscribed Lambda, or the AWS Chatbot integration).
"""
from __future__ import annotations
import json
import os

import boto3

TOPIC_ARN = os.environ.get("GUARDIAN_SNS_TOPIC_ARN", "")


def _severity_emoji(decision) -> str:
    if decision.highest_priority:
        return "\U0001F512"  # lock
    if decision.action == "hold":
        return "\u26A0\uFE0F"  # warning
    return "\u2705"  # check


def format_message(repo: str, pr_number: str, decision) -> str:
    emoji = _severity_emoji(decision)
    header = f"{emoji} Terraform plan {'HELD' if decision.action == 'hold' else 'auto-applied'} -- {repo}, PR #{pr_number}"
    lines = [header]

    if decision.oidc_diff and decision.oidc_diff.changed:
        lines.append(f"Risk: OIDC trust policy {'widened' if decision.oidc_diff.widened else 'changed'}")
        short_key = "sub" if "sub" in (decision.oidc_diff.key or "") else "aud"
        before = decision.oidc_diff.before.patterns if decision.oidc_diff.before else []
        after = decision.oidc_diff.after.patterns if decision.oidc_diff.after else []
        lines.append(f"  {short_key}: {', '.join(before) or '(none)'} -> {', '.join(after) or '(none)'}")
        if decision.oidc_diff.examples_newly_allowed:
            examples = "; ".join(decision.oidc_diff.examples_newly_allowed)
            lines.append(f"This would newly allow, e.g.: {examples}")
    elif decision.risk_flags:
        top = sorted(decision.risk_flags, key=lambda f: {"critical": 0, "warn": 1, "info": 2}[f.severity])[0]
        lines.append(f"Risk: {top.message}")
    else:
        lines.append("No IAM/security resources touched.")

    lines.append(f"Cost impact: {'+' if decision.cost_delta_usd >= 0 else ''}${decision.cost_delta_usd:.2f}/mo (est.)")

    if decision.action == "hold":
        lines.append("[Approve & Apply]  [View full plan]  [Reject]")

    return "\n".join(lines)


def notify(repo: str, pr_number: str, decision, plan_url: str = "") -> None:
    message = format_message(repo, pr_number, decision)
    if not TOPIC_ARN:
        # Local/dev/test path: never silently drop a hold notification.
        print("[sns_notify] GUARDIAN_SNS_TOPIC_ARN not set, printing instead:\n" + message)
        return

    sns = boto3.client("sns")
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject=f"Terraform Guardian: {repo} PR #{pr_number} -- {decision.action}",
        Message=message,
        MessageAttributes={
            "action": {"DataType": "String", "StringValue": decision.action},
            "highest_priority": {"DataType": "String", "StringValue": str(decision.highest_priority)},
        },
    )
