import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.plan_parser import parse_plan_json
from agent.cost_estimate import estimate_cost_delta
from agent.decision_engine import evaluate


def decide(*changes, known=None):
    plan = json.dumps({"resource_changes": list(changes)})
    parsed = parse_plan_json(plan)
    cost = estimate_cost_delta(parsed.resource_changes, baseline_usd=5.0)
    return evaluate(parsed, cost, known_resource_types=known if known is not None else {c["type"] for c in changes})


def rc(rtype, actions, before, after, name="x"):
    return {"address": f"{rtype}.{name}", "type": rtype, "name": name,
            "change": {"actions": actions, "before": before, "after": after}}


def codes(decision):
    return [f.code for f in decision.risk_flags]


def sg_ingress(cidr, port):
    return {"ingress": [{"cidr_blocks": [cidr], "from_port": port, "to_port": port, "protocol": "tcp"}]}


def test_ssh_opened_to_world_holds_as_critical():
    d = decide(rc("aws_security_group", ["update"], sg_ingress("10.0.0.0/8", 22), sg_ingress("0.0.0.0/0", 22)))
    assert d.action == "hold"
    flag = next(f for f in d.risk_flags if f.code == "NETWORK_OPEN_TO_WORLD")
    assert flag.severity == "critical" and "tcp/22" in flag.message


def test_web_port_open_to_world_still_holds_but_is_warn():
    d = decide(rc("aws_security_group", ["create"], None, sg_ingress("0.0.0.0/0", 443)))
    assert d.action == "hold"
    assert next(f for f in d.risk_flags if f.code == "NETWORK_OPEN_TO_WORLD").severity == "warn"


def test_preexisting_open_rule_is_not_reflagged():
    same = sg_ingress("0.0.0.0/0", 443)
    d = decide(rc("aws_security_group", ["update"], same, same))
    assert "NETWORK_OPEN_TO_WORLD" not in codes(d)


def test_private_ingress_auto_applies():
    d = decide(rc("aws_security_group", ["create"], None, sg_ingress("10.0.0.0/8", 5432)))
    assert d.action == "auto_apply"


def test_removing_a_rule_never_flags():
    d = decide(rc("aws_security_group", ["delete"], sg_ingress("0.0.0.0/0", 22), None))
    assert "NETWORK_OPEN_TO_WORLD" not in codes(d)


def test_ipv6_world_and_standalone_rule_types():
    d = decide(rc("aws_vpc_security_group_ingress_rule", ["create"], None,
                  {"cidr_ipv6": "::/0", "from_port": 3389, "to_port": 3389, "ip_protocol": "tcp"}))
    assert d.action == "hold" and "NETWORK_OPEN_TO_WORLD" in codes(d)
    d = decide(rc("aws_security_group_rule", ["create"], None,
                  {"type": "ingress", "cidr_blocks": ["0.0.0.0/0"], "from_port": 0, "to_port": 65535, "protocol": "tcp"}))
    assert d.action == "hold"


def test_s3_public_access_block_disabled_holds():
    before = {k: True for k in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")}
    after = dict(before, block_public_policy=False)
    d = decide(rc("aws_s3_bucket_public_access_block", ["update"], before, after))
    assert d.action == "hold"
    assert "block_public_policy" in next(f for f in d.risk_flags if f.code == "S3_PUBLIC_ACCESS_LOOSENED").message


def test_s3_public_access_block_all_true_is_safe():
    on = {k: True for k in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")}
    assert decide(rc("aws_s3_bucket_public_access_block", ["create"], None, on)).action == "auto_apply"


def test_s3_public_acl_and_public_policy_hold():
    assert decide(rc("aws_s3_bucket_acl", ["create"], None, {"acl": "public-read"})).action == "hold"
    public = json.dumps({"Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject", "Resource": "*"}]})
    assert decide(rc("aws_s3_bucket_policy", ["create"], None, {"policy": public})).action == "hold"


def test_conditioned_or_private_bucket_policy_is_not_public():
    scoped = json.dumps({"Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject",
                                        "Resource": "*", "Condition": {"StringEquals": {"aws:SourceVpce": "vpce-1"}}}]})
    assert decide(rc("aws_s3_bucket_policy", ["create"], None, {"policy": scoped})).action == "auto_apply"


def test_public_database_and_encryption_off_hold():
    assert decide(rc("aws_db_instance", ["update"], {"publicly_accessible": False}, {"publicly_accessible": True}),
                  known={"aws_db_instance"}).action == "hold"
    d = decide(rc("aws_ebs_volume", ["create"], None, {"encrypted": False}))
    assert d.action == "hold" and "ENCRYPTION_DISABLED" in codes(d)


def test_security_flags_and_iam_touch_are_reported_together():
    d = decide(
        rc("aws_security_group", ["create"], None, sg_ingress("0.0.0.0/0", 22), name="a"),
        rc("aws_iam_role_policy", ["update"], {"policy": "{}"}, {"policy": "{}"}, name="b"),
    )
    assert d.action == "hold"
    assert {"NETWORK_OPEN_TO_WORLD", "IAM_RESOURCE_TOUCHED"} <= set(codes(d))
