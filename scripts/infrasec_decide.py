#!/usr/bin/env python3
"""InfraSec offline gate.

Runs the deterministic decision engine on a `terraform show -json` plan with no
AWS account or network. Intended for the GitLab pipeline (hands-off loop).

  python scripts/infrasec_decide.py --plan plan.json --ci-status pass

Writes infrasec-decision.json and infrasec-report.md.
Exit codes: 0 = pass, 2 = held by InfraSec, 3 = conventional CI failed.

`--ci-status` is what the ordinary CI checks (fmt/validate/tests) said. It lets
the report say honestly whether InfraSec was the thing that stopped the change
(value_added = "gate") or whether CI was going to fail anyway
(value_added = "diagnosis": InfraSec only explains and proposes the fix).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.plan_parser import parse_plan_json  # noqa: E402
from agent.cost_estimate import estimate_cost_delta  # noqa: E402
from agent.decision_engine import evaluate  # noqa: E402
from agent.fix_hints import FIX_HINTS, AUTO_FIXABLE  # noqa: E402


MAX_AUTOFIX_ATTEMPTS = 2


def value_added(action: str, ci_status: str) -> str:
    if action == "auto_apply":
        return "none"
    return {"pass": "gate", "fail": "diagnosis"}.get(ci_status, "unverified")


VALUE_TEXT = {
    "none": "Nothing to add: the change is safe and CI passed.",
    "gate": "**CI alone would have shipped this.** Every conventional check passed. InfraSec is the only thing that stopped it.",
    "diagnosis": "CI was already failing, so InfraSec is not the gate here. It adds the diagnosis and a proposed fix only.",
    "unverified": "CI status was not provided, so it is unknown whether CI alone would have caught this.",
}


def build_report(decision: dict, ci_status: str, added: str, attempt: int) -> str:
    action = decision["action"]
    head = "PASS" if action == "auto_apply" and ci_status != "fail" else "HELD"
    lines = [f"## InfraSec: **{head}**", ""]
    lines.append(f"- Conventional CI (fmt / validate / tests): **{ci_status.upper()}**")
    lines.append(f"- InfraSec decision: **{action}** (confidence {decision['confidence']:.2f})")
    lines.append(f"- Value added: {VALUE_TEXT[added]}")
    if attempt:
        lines.append(f"- Auto-fix attempts so far: {attempt} of {MAX_AUTOFIX_ATTEMPTS}")
    if head == "HELD" and attempt >= MAX_AUTOFIX_ATTEMPTS:
        lines.append("- **Auto-fix budget used up: escalated to a human.**")
    lines += ["", f"**Why:** {decision['reasoning']}", ""]
    flags = decision["risk_flags"]
    if flags:
        lines += ["| Severity | Code | Finding | How to fix | Agent may auto-fix |", "|---|---|---|---|---|"]
        for f in flags:
            fixable = "yes" if f["code"] in AUTO_FIXABLE else "no, needs a human"
            lines.append(f"| {f['severity']} | `{f['code']}` | {f['message']} | {FIX_HINTS.get(f['code'], '')} | {fixable} |")
    elif action == "auto_apply":
        lines.append("No findings. Safe to deploy.")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="InfraSec offline gate")
    ap.add_argument("--plan", default="plan.json")
    ap.add_argument("--known-types", default=".infrasec/known_types.json")
    ap.add_argument("--baseline-usd", type=float, default=float(os.environ.get("BASELINE_USD", "5")))
    ap.add_argument("--ci-status", choices=["pass", "fail", "unknown"], default=os.environ.get("CI_STATUS", "unknown"))
    ap.add_argument("--attempt", type=int, default=int(os.environ.get("INFRASEC_ATTEMPT", "0")))
    ap.add_argument("--out-dir", default=".")
    args = ap.parse_args(argv)

    known: set[str] = set()
    kt = Path(args.known_types)
    if kt.exists():
        known = set(json.loads(kt.read_text()))

    parsed = parse_plan_json(Path(args.plan).read_text(encoding="utf-8"))
    cost = estimate_cost_delta(parsed.resource_changes, baseline_usd=args.baseline_usd)
    decision = evaluate(parsed, cost, known_resource_types=known).to_dict()
    added = value_added(decision["action"], args.ci_status)
    decision.update(ci_status=args.ci_status, value_added=added, attempt=args.attempt)

    out = Path(args.out_dir)
    (out / "infrasec-decision.json").write_text(json.dumps(decision, indent=2))
    report = build_report(decision, args.ci_status, added, args.attempt)
    (out / "infrasec-report.md").write_text(report)
    print(report)

    if args.ci_status == "fail":
        return 3
    return 0 if decision["action"] == "auto_apply" else 2


if __name__ == "__main__":
    sys.exit(main())
