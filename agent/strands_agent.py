"""Strands agent wrapper for Infra Cost Guardian.

The high-stakes verdict stays deterministic: parsing, OIDC diffing, cost
estimation, and the final hold/auto-apply gate are plain Python tools. The
Strands agent exposes those tools as the agent surface for demos, tracing,
and future reviewer-facing explanations without letting an LLM override the
security decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cost_estimate import CostEstimateResult, estimate_cost_delta
from .decision_engine import Decision, evaluate
from .plan_parser import ParsedPlan, ResourceChange, parse_plan_json

try:
    from strands import Agent, tool
except ImportError:  # pragma: no cover - exercised when SDK is absent locally
    Agent = None

    def tool(func=None, **_kwargs):
        if func is None:
            return lambda wrapped: wrapped
        return func


SYSTEM_PROMPT = """
You are Infra Cost Guardian, a background infrastructure-review agent.
Use the provided deterministic tools to inspect Terraform plan JSON, estimate
cost impact, and decide whether a change can auto-apply or must be held for a
human. Never override the deterministic decision tool. Your job is to explain
the verdict clearly and surface only real decisions.
""".strip()


@dataclass
class GuardianReview:
    parsed_plan: ParsedPlan
    cost_result: CostEstimateResult
    decision: Decision
    tool_trace: list[str]


def _resource_change_to_dict(rc: ResourceChange) -> dict[str, Any]:
    return {
        "address": rc.address,
        "type": rc.type,
        "name": rc.name,
        "actions": rc.actions,
        "provider_name": rc.provider_name,
        "is_replace": rc.is_replace,
        "is_iam_related": rc.is_iam_related,
        "has_trust_policy": rc.has_trust_policy,
    }


@tool
def terraform_plan_parse(plan_json: str) -> dict[str, Any]:
    """Parse Terraform plan JSON into normalized resource-change facts.

    Args:
        plan_json: Output from `terraform show -json tfplan.binary`.

    Returns:
        A JSON-serializable summary of parse status, resource changes, IAM
        touches, new resource types, and unknown action signals.
    """
    parsed = parse_plan_json(plan_json)
    return {
        "parse_ok": parsed.parse_ok,
        "parse_error": parsed.parse_error,
        "resource_change_count": len(parsed.resource_changes),
        "resource_changes": [_resource_change_to_dict(rc) for rc in parsed.resource_changes],
        "new_resource_types": sorted(parsed.new_resource_types),
        "touched_iam": [rc.address for rc in parsed.touched_iam],
        "has_unknown_action": parsed.has_unknown_action,
    }


@tool
def terraform_cost_estimate(plan_json: str, baseline_usd: float = 5.0) -> dict[str, Any]:
    """Estimate monthly cost impact for a Terraform plan.

    Args:
        plan_json: Output from `terraform show -json tfplan.binary`.
        baseline_usd: Current monthly baseline used for percent thresholding.

    Returns:
        Cost delta, baseline, percent of baseline, estimator method, and
        per-resource estimate details.
    """
    parsed = parse_plan_json(plan_json)
    if not parsed.parse_ok:
        return {
            "delta_usd": 0.0,
            "baseline_usd": baseline_usd,
            "pct_of_baseline": 0.0,
            "method": "n/a",
            "per_resource": {},
            "notes": "Plan did not parse; cost estimate skipped because decision will fail closed.",
            "exceeds_threshold": False,
        }

    cost = estimate_cost_delta(parsed.resource_changes, baseline_usd)
    return {
        "delta_usd": cost.delta_usd,
        "baseline_usd": cost.baseline_usd,
        "pct_of_baseline": cost.pct_of_baseline,
        "method": cost.method,
        "per_resource": cost.per_resource or {},
        "notes": cost.notes,
        "exceeds_threshold": cost.exceeds_threshold,
    }


@tool
def guardian_decision(
    plan_json: str,
    known_resource_types: list[str] | None = None,
    baseline_usd: float = 5.0,
) -> dict[str, Any]:
    """Decide whether a Terraform plan auto-applies or holds for review.

    Args:
        plan_json: Output from `terraform show -json tfplan.binary`.
        known_resource_types: Resource types previously seen in this repo.
        baseline_usd: Current monthly baseline used for cost thresholding.

    Returns:
        The final deterministic guardian verdict. This tool is the authority;
        the agent may explain it, but may not override it.
    """
    parsed = parse_plan_json(plan_json)
    if parsed.parse_ok:
        cost = estimate_cost_delta(parsed.resource_changes, baseline_usd)
    else:
        cost = CostEstimateResult(
            delta_usd=0.0,
            baseline_usd=baseline_usd,
            pct_of_baseline=0.0,
            method="n/a",
        )
    decision = evaluate(parsed, cost, set(known_resource_types or []))
    return decision.to_dict()


def build_strands_agent():
    """Build the Strands Agent used for demos and future rich explanations."""
    if Agent is None:
        raise RuntimeError("strands-agents is not installed")

    return Agent(
        tools=[terraform_plan_parse, terraform_cost_estimate, guardian_decision],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
    )


def run_guardian_review(
    plan_json: str,
    baseline_usd: float,
    known_resource_types: set[str],
) -> GuardianReview:
    """Run the production review path through the Strands-exposed tools.

    This function avoids an LLM call in the Lambda hot path, keeping the
    verdict fast, repeatable, and fail-closed while still making the agent's
    tools explicit and available to Strands.
    """
    parsed = parse_plan_json(plan_json)
    if parsed.parse_ok:
        cost = estimate_cost_delta(parsed.resource_changes, baseline_usd)
    else:
        cost = CostEstimateResult(
            delta_usd=0.0,
            baseline_usd=baseline_usd,
            pct_of_baseline=0.0,
            method="n/a",
        )
    decision = evaluate(parsed, cost, known_resource_types)
    return GuardianReview(
        parsed_plan=parsed,
        cost_result=cost,
        decision=decision,
        tool_trace=[
            "terraform_plan_parse",
            "terraform_cost_estimate",
            "guardian_decision",
        ],
    )
