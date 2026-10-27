import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.oidc_diff import diff_trust_policy

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


def test_catches_sub_widening():
    plan = load("plan_oidc_trap.json")
    change = plan["resource_changes"][0]["change"]
    result = diff_trust_policy(change["before"]["assume_role_policy"], change["after"]["assume_role_policy"])
    assert result.changed
    assert result.widened, "must detect the sub claim widening"
    assert result.key == "token.actions.githubusercontent.com:sub"
    assert "repo:you/repo:ref:refs/heads/main" in result.before.patterns
    assert "repo:you/repo:*" in result.after.patterns
    assert result.examples_newly_allowed, "should produce a concrete newly-allowed example"


def test_no_change_reports_unchanged():
    same_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Condition": {
                "StringEquals": {
                    "token.actions.githubusercontent.com:sub": "repo:you/repo:ref:refs/heads/main"
                }
            }
        }]
    })
    result = diff_trust_policy(same_policy, same_policy)
    assert not result.changed


def test_narrowing_is_not_flagged_as_widened():
    before = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Condition": {
            "StringLike": {"token.actions.githubusercontent.com:sub": "repo:you/repo:*"}
        }}]
    })
    after = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Condition": {
            "StringEquals": {"token.actions.githubusercontent.com:sub": "repo:you/repo:ref:refs/heads/main"}
        }}]
    })
    result = diff_trust_policy(before, after)
    assert result.changed
    assert not result.widened
    assert result.narrowed


def test_handles_missing_policy_gracefully():
    result = diff_trust_policy(None, None)
    assert not result.changed


if __name__ == "__main__":
    test_catches_sub_widening()
    test_no_change_reports_unchanged()
    test_narrowing_is_not_flagged_as_widened()
    test_handles_missing_policy_gracefully()
    print("test_oidc_diff: all passed")
