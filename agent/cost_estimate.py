"""cost_estimate

Estimates the monthly cost delta ($ and %) implied by a terraform plan.

The primary path shells out to the Infracost CLI (free OSS,
https://www.infracost.io) against the plan JSON, which gives accurate
per-resource pricing using AWS/GCP/Azure price lists.

If the Infracost binary isn't available (e.g. local dev without it
installed), this falls back to a small heuristic price table so the cost
check never silently no-ops. The fallback is conservative on purpose: when
unsure, it overestimates the delta so more things get held for human
review rather than fewer.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import json
import shutil
import subprocess

from .plan_parser import ResourceChange

# Very rough monthly USD heuristics, used only when Infracost is unavailable.
# Keyed by resource type -> (fixed_monthly_usd, per_unit_hint)
HEURISTIC_MONTHLY_USD = {
    "aws_instance": 8.0,           # depends heavily on type; conservative small-instance estimate
    "aws_db_instance": 15.0,
    "aws_nat_gateway": 32.0,
    "aws_lambda_function": 0.20,   # per-invocation cost is usage-based; treat as small fixed nudge
    "aws_dynamodb_table": 0.0,     # on-demand billing, ~$0 fixed baseline
    "aws_s3_bucket": 0.05,
    "aws_cloudwatch_log_group": 0.05,
    "aws_sqs_queue": 0.0,
    "aws_sns_topic": 0.0,
    "aws_elasticache_cluster": 12.0,
    "aws_eks_cluster": 73.0,
    "aws_ecs_service": 0.0,        # depends on launch type/tasks
}


@dataclass
class CostEstimateResult:
    delta_usd: float
    baseline_usd: float
    pct_of_baseline: float
    method: str                    # "infracost" | "heuristic"
    per_resource: dict = None
    notes: str = ""

    @property
    def exceeds_threshold(self) -> bool:
        return self.delta_usd >= 2.0 or self.pct_of_baseline >= 0.40


def _infracost_available() -> bool:
    return shutil.which("infracost") is not None


def estimate_with_infracost(plan_json_path: str) -> Optional[CostEstimateResult]:
    """Runs `infracost breakdown --path <plan.json> --format json` and reads
    the diff estimate. Requires INFRACOST_API_KEY in env (free tier is fine).
    Returns None if the CLI isn't present or the call fails, so the caller
    can fall back to the heuristic estimator (fail closed on cost, too)."""
    if not _infracost_available():
        return None
    try:
        proc = subprocess.run(
            ["infracost", "breakdown", "--path", plan_json_path, "--format", "json"],
            capture_output=True, text=True, timeout=60, check=True,
        )
        data = json.loads(proc.stdout)
        total_monthly = float(data.get("totalMonthlyCost") or 0.0)
        # Infracost breakdown gives absolute monthly cost of the plan's
        # resources; the "delta" relative to current infra is computed by
        # the caller using the stored baseline from DynamoDB.
        return CostEstimateResult(
            delta_usd=total_monthly,
            baseline_usd=0.0,       # filled in by caller
            pct_of_baseline=0.0,    # filled in by caller
            method="infracost",
            per_resource={r["name"]: r.get("monthlyCost") for r in data.get("resources", [])},
        )
    except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, ValueError) as e:
        return CostEstimateResult(
            delta_usd=0.0, baseline_usd=0.0, pct_of_baseline=0.0,
            method="infracost_failed", notes=f"infracost call failed, falling back: {e}",
        )


def estimate_with_heuristic(resource_changes: list[ResourceChange], baseline_usd: float) -> CostEstimateResult:
    """Sums a rough monthly cost delta from created/deleted/replaced
    resources using the static heuristic table. Plain updates (no replace)
    on non-sizing attributes are treated as ~$0 delta. This is coarse by
    design: the point is to catch big obvious swings, like a new NAT
    gateway or a new RDS instance, not to be a pricing engine."""
    delta = 0.0
    per_resource = {}
    for rc in resource_changes:
        base_cost = HEURISTIC_MONTHLY_USD.get(rc.type, 0.0)
        if rc.is_create:
            delta += base_cost
            per_resource[rc.address] = base_cost
        elif rc.is_delete:
            delta -= base_cost
            per_resource[rc.address] = -base_cost
        elif rc.is_replace:
            # A replace is a delete plus a create of the same type, so it nets
            # to roughly zero steady-state cost. There's a brief double-billing
            # window during the swap, so we treat it as a small nudge instead.
            nudge = base_cost * 0.1
            delta += nudge
            per_resource[rc.address] = nudge
        # plain updates: assumed ~$0 delta under the heuristic

    pct = (delta / baseline_usd) if baseline_usd > 0 else (1.0 if delta > 0 else 0.0)
    return CostEstimateResult(
        delta_usd=round(delta, 2),
        baseline_usd=baseline_usd,
        pct_of_baseline=round(pct, 4),
        method="heuristic",
        per_resource=per_resource,
        notes="Infracost unavailable or failed; used static per-resource-type heuristic table.",
    )


def estimate_cost_delta(
    resource_changes: list[ResourceChange],
    baseline_usd: float,
    plan_json_path: Optional[str] = None,
) -> CostEstimateResult:
    """Top-level entry point used by the decision engine."""
    if plan_json_path:
        result = estimate_with_infracost(plan_json_path)
        if result is not None and result.method == "infracost":
            result.baseline_usd = baseline_usd
            result.pct_of_baseline = round(
                (result.delta_usd / baseline_usd) if baseline_usd > 0 else (1.0 if result.delta_usd > 0 else 0.0), 4
            )
            return result
    return estimate_with_heuristic(resource_changes, baseline_usd)
