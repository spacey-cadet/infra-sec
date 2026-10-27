import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.plan_parser import parse_plan_json
from agent.cost_estimate import estimate_cost_delta
from agent.decision_engine import evaluate

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


def test_safe_plan_auto_applies():
    parsed = parse_plan_json(load("plan_safe.json"))
    cost = estimate_cost_delta(parsed.resource_changes, baseline_usd=5.0)
    decision = evaluate(parsed, cost, known_resource_types={"aws_lambda_function"})
    assert decision.action == "auto_apply"


def test_cost_heavy_plan_holds():
    parsed = parse_plan_json(load("plan_cost.json"))
    cost = estimate_cost_delta(parsed.resource_changes, baseline_usd=5.0)
    decision = evaluate(parsed, cost, known_resource_types={"aws_nat_gateway"})
    assert decision.action == "hold"
    assert any(f.code == "COST_THRESHOLD_EXCEEDED" for f in decision.risk_flags)


def test_oidc_widening_holds_with_highest_priority():
    parsed = parse_plan_json(load("plan_oidc_trap.json"))
    cost = estimate_cost_delta(parsed.resource_changes, baseline_usd=5.0)
    decision = evaluate(parsed, cost, known_resource_types={"aws_iam_role"})
    assert decision.action == "hold"
    assert decision.highest_priority, "OIDC widening must be flagged as the highest priority hold"
    assert decision.oidc_diff is not None
    assert decision.oidc_diff.widened


def test_malformed_plan_fails_closed():
    parsed = parse_plan_json(load("plan_malformed.json"))
    cost = estimate_cost_delta(parsed.resource_changes, baseline_usd=5.0)
    decision = evaluate(parsed, cost, known_resource_types=set())
    assert decision.action == "hold"
    assert any(f.code == "PARSE_ERROR" for f in decision.risk_flags)


def test_new_resource_type_holds():
    # plan_cost.json creates an aws_nat_gateway (a "create" action, so it can
    # trip the new-resource-type check); with no prior history for that type
    # the new-resource-type rule should fire (it's checked before the cost
    # threshold rule in the escalation matrix).
    parsed = parse_plan_json(load("plan_cost.json"))
    cost = estimate_cost_delta(parsed.resource_changes, baseline_usd=5.0)
    decision = evaluate(parsed, cost, known_resource_types=set())  # nothing known yet
    assert decision.action == "hold"
    assert any(f.code == "NEW_RESOURCE_TYPE" for f in decision.risk_flags)


if __name__ == "__main__":
    test_safe_plan_auto_applies()
    test_cost_heavy_plan_holds()
    test_oidc_widening_holds_with_highest_priority()
    test_malformed_plan_fails_closed()
    test_new_resource_type_holds()
    print("test_decision_engine: all passed")
