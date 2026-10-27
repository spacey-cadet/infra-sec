import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.plan_parser import parse_plan_json

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


def test_parses_safe_plan():
    parsed = parse_plan_json(load("plan_safe.json"))
    assert parsed.parse_ok
    assert len(parsed.resource_changes) == 1
    rc = parsed.resource_changes[0]
    assert rc.type == "aws_lambda_function"
    assert rc.actions == ["update"]
    assert not rc.is_iam_related


def test_parses_iam_plan():
    parsed = parse_plan_json(load("plan_oidc_trap.json"))
    assert parsed.parse_ok
    rc = parsed.resource_changes[0]
    assert rc.is_iam_related
    assert rc.has_trust_policy


def test_fails_closed_on_malformed_plan():
    parsed = parse_plan_json(load("plan_malformed.json"))
    assert not parsed.parse_ok
    assert parsed.parse_error is not None


def test_fails_closed_on_garbage_input():
    parsed = parse_plan_json("not even json{{{")
    assert not parsed.parse_ok


if __name__ == "__main__":
    test_parses_safe_plan()
    test_parses_iam_plan()
    test_fails_closed_on_malformed_plan()
    test_fails_closed_on_garbage_input()
    print("test_plan_parser: all passed")
