"""decision_engine

Implements the escalation matrix as plain, deterministic, testable Python.

This module is an OR-gate over independent risk checks. Any single check
that fires routes to "hold." There is no averaging, no "mostly safe"
scoring, no weighting that could let a serious risk get diluted by a bunch
of boring changes in the same plan. It also fails closed: parse errors,
unknown actions, and unrecognized resource types with no history all route
to "hold" too.

An optional LLM call can sit on top of this verdict to produce a
human-readable explanation and help a reviewer prioritize among multiple
held risks. It cannot flip auto_apply to hold or vice versa; the matrix
result below is final.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from .plan_parser import ParsedPlan, ResourceChange
from .oidc_diff import diff_trust_policy, OidcDiffResult
from .cost_estimate import CostEstimateResult

COST_THRESHOLD_USD = 2.0
COST_THRESHOLD_PCT = 0.40


@dataclass
class RiskFlag:
    code: str
    message: str
    severity: str  # "info" | "warn" | "critical"


@dataclass
class Decision:
    action: str  # "auto_apply" | "hold"
    reasoning: str
    risk_flags: list[RiskFlag] = field(default_factory=list)
    cost_delta_usd: float = 0.0
    confidence: float = 1.0
    oidc_diff: Optional[OidcDiffResult] = None
    highest_priority: bool = False  # True for the OIDC-widening special case

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "reasoning": self.reasoning,
            "risk_flags": [f.__dict__ for f in self.risk_flags],
            "cost_delta_usd": self.cost_delta_usd,
            "confidence": self.confidence,
            "highest_priority": self.highest_priority,
            "oidc_diff": (
                {
                    "changed": self.oidc_diff.changed,
                    "widened": self.oidc_diff.widened,
                    "key": self.oidc_diff.key,
                    "before": self.oidc_diff.before.patterns if self.oidc_diff.before else None,
                    "after": self.oidc_diff.after.patterns if self.oidc_diff.after else None,
                    "explanation": self.oidc_diff.explanation,
                    "examples_newly_allowed": self.oidc_diff.examples_newly_allowed,
                }
                if self.oidc_diff else None
            ),
        }


def evaluate(
    parsed_plan: ParsedPlan,
    cost_result: CostEstimateResult,
    known_resource_types: set[str],
) -> Decision:
    """Runs the full escalation matrix against a parsed plan + cost estimate.
    `known_resource_types` is the set of resource types this repo's plan
    history has seen before (from DynamoDB); anything new triggers a hold.
    """
    flags: list[RiskFlag] = []

    # Fail-closed gate: unparseable plan.
    if not parsed_plan.parse_ok:
        return Decision(
            action="hold",
            reasoning=f"Plan failed to parse cleanly ({parsed_plan.parse_error}). Failing closed.",
            risk_flags=[RiskFlag("PARSE_ERROR", parsed_plan.parse_error or "unknown parse error", "critical")],
            cost_delta_usd=0.0,
            confidence=1.0,
        )

    if parsed_plan.has_unknown_action:
        flags.append(RiskFlag("UNKNOWN_ACTION", "Plan contains a resource action outside the known set (no-op/create/read/update/delete).", "critical"))

    # OIDC trust policy check: highest priority, special-cased.
    oidc_result: Optional[OidcDiffResult] = None
    for rc in parsed_plan.resource_changes:
        if rc.has_trust_policy or rc.is_oidc_provider:
            before_policy = (rc.before or {}).get("assume_role_policy")
            after_policy = (rc.after or {}).get("assume_role_policy")
            if before_policy is None and after_policy is None:
                continue
            diff = diff_trust_policy(before_policy, after_policy)
            if diff.changed:
                oidc_result = diff
                if diff.widened:
                    flags.append(RiskFlag(
                        "OIDC_TRUST_WIDENED",
                        f"{rc.address}: {diff.explanation}",
                        "critical",
                    ))
                else:
                    flags.append(RiskFlag(
                        "OIDC_TRUST_CHANGED",
                        f"{rc.address}: {diff.explanation}",
                        "warn",
                    ))
                break  # one widened OIDC change is enough to force a hold; stop scanning

    if oidc_result is not None and oidc_result.widened:
        return Decision(
            action="hold",
            reasoning=(
                "OIDC trust policy condition was widened. This is the single highest-priority "
                "risk this agent exists to catch, so it escalates regardless of any other signal."
            ),
            risk_flags=flags,
            cost_delta_usd=cost_result.delta_usd,
            confidence=0.98,
            oidc_diff=oidc_result,
            highest_priority=True,
        )

    # IAM/policy resource types touched at all.
    iam_touches = parsed_plan.touched_iam
    if iam_touches:
        for rc in iam_touches:
            flags.append(RiskFlag(
                "IAM_RESOURCE_TOUCHED",
                f"{rc.address} ({rc.type}) is an IAM/policy resource and was {'/'.join(rc.actions)}.",
                "warn",
            ))
        return Decision(
            action="hold",
            reasoning="Plan touches one or more IAM/policy resource types. Always escalated regardless of the specific diff.",
            risk_flags=flags,
            cost_delta_usd=cost_result.delta_usd,
            confidence=0.95,
            oidc_diff=oidc_result,
        )

    # New resource type never seen before in this repo's history.
    new_types = parsed_plan.new_resource_types - known_resource_types
    if new_types:
        flags.append(RiskFlag(
            "NEW_RESOURCE_TYPE",
            f"Resource type(s) not seen before in this repo's plan history: {sorted(new_types)}.",
            "warn",
        ))
        return Decision(
            action="hold",
            reasoning="Plan introduces a resource type with no prior history in this repo. Escalating for a first-look human review.",
            risk_flags=flags,
            cost_delta_usd=cost_result.delta_usd,
            confidence=0.85,
        )

    # Cost threshold.
    if cost_result.exceeds_threshold:
        flags.append(RiskFlag(
            "COST_THRESHOLD_EXCEEDED",
            f"Estimated cost delta ${cost_result.delta_usd:.2f}/mo "
            f"({cost_result.pct_of_baseline * 100:.0f}% of baseline ${cost_result.baseline_usd:.2f}/mo) "
            f"exceeds threshold ($2/mo or 40% of baseline).",
            "warn",
        ))
        return Decision(
            action="hold",
            reasoning="Estimated monthly cost delta exceeds the configured threshold.",
            risk_flags=flags,
            cost_delta_usd=cost_result.delta_usd,
            confidence=0.9,
        )

    # Resource replacement on a non-sensitive resource still auto-applies.
    replacements = [rc for rc in parsed_plan.resource_changes if rc.is_replace]
    if replacements:
        for rc in replacements:
            flags.append(RiskFlag(
                "NON_SENSITIVE_REPLACE",
                f"{rc.address} ({rc.type}) will be replaced (destroy+create), but is not IAM/OIDC and cost delta is within threshold.",
                "info",
            ))

    # Nothing tripped, so auto-apply.
    return Decision(
        action="auto_apply",
        reasoning="No IAM/OIDC resources touched, no new-to-repo resource types, cost delta within threshold.",
        risk_flags=flags,
        cost_delta_usd=cost_result.delta_usd,
        confidence=0.97,
        oidc_diff=oidc_result,
    )
