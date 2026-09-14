import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.strands_agent import guardian_decision, run_guardian_review, terraform_plan_parse

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


def test_strands_parse_tool_exposes_plan_facts():
    summary = terraform_plan_parse(load("plan_safe.json"))
    assert summary["parse_ok"]
    assert summary["resource_change_count"] == 1
    assert summary["resource_changes"][0]["type"] == "aws_lambda_function"


def test_strands_decision_tool_keeps_oidc_widening_authoritative():
    decision = guardian_decision(
        load("plan_oidc_trap.json"),
        known_resource_types=["aws_iam_role"],
        baseline_usd=5.0,
    )
    assert decision["action"] == "hold"
    assert decision["highest_priority"]
    assert decision["oidc_diff"]["widened"]


def test_lambda_review_path_uses_strands_tool_sequence():
    review = run_guardian_review(
        load("plan_safe.json"),
        baseline_usd=5.0,
        known_resource_types={"aws_lambda_function"},
    )
    assert review.decision.action == "auto_apply"
    assert review.tool_trace == [
        "terraform_plan_parse",
        "terraform_cost_estimate",
        "guardian_decision",
    ]


if __name__ == "__main__":
    test_strands_parse_tool_exposes_plan_facts()
    test_strands_decision_tool_keeps_oidc_widening_authoritative()
    test_lambda_review_path_uses_strands_tool_sequence()
    print("test_strands_agent: all passed")
