"""security_checks

Deterministic detectors for *silent security loosening* on resources that are
NOT IAM/OIDC (those are handled by oidc_diff + the IAM gate). These are the
changes that pass `terraform validate`, `plan` and `apply` and that a normal CI
pipeline will happily ship:

  NETWORK_OPEN_TO_WORLD       ingress newly open to 0.0.0.0/0 or ::/0
  S3_PUBLIC_ACCESS_LOOSENED   public-access-block flag off, public ACL, or
                              bucket policy granting Principal "*"
  DB_PUBLICLY_ACCESSIBLE      RDS instance made publicly_accessible
  ENCRYPTION_DISABLED         storage/volume encryption explicitly off

Every check compares `after` against `before` so a pre-existing setting that
did not change is not re-flagged. A resource being deleted is never flagged
(removing something cannot loosen it). Any returned flag means "hold".
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from .plan_parser import ResourceChange

WORLD_V4 = "0.0.0.0/0"
WORLD_V6 = "::/0"
WEB_PORTS = {80, 443}
PUBLIC_ACLS = {"public-read", "public-read-write", "authenticated-read"}
PAB_FLAGS = ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")


def _flag(code: str, message: str, severity: str):
    # Imported lazily to avoid a circular import with decision_engine.
    from .decision_engine import RiskFlag
    return RiskFlag(code, message, severity)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _world_open(rc_type: str, doc: Optional[dict]) -> set[tuple]:
    """Return {(from_port, to_port, protocol)} that are open to the world."""
    if not doc:
        return set()
    out: set[tuple] = set()

    def add(block: dict, v4: Iterable, v6: Iterable, proto_key: str = "protocol"):
        cidrs = set(_as_list(v4)) | set(_as_list(v6))
        if WORLD_V4 in cidrs or WORLD_V6 in cidrs:
            out.add((block.get("from_port"), block.get("to_port"), str(block.get(proto_key))))

    if rc_type == "aws_security_group":
        for block in _as_list(doc.get("ingress")):
            if isinstance(block, dict):
                add(block, block.get("cidr_blocks"), block.get("ipv6_cidr_blocks"))
    elif rc_type == "aws_security_group_rule":
        if doc.get("type") == "ingress":
            add(doc, doc.get("cidr_blocks"), doc.get("ipv6_cidr_blocks"))
    elif rc_type == "aws_vpc_security_group_ingress_rule":
        add(doc, doc.get("cidr_ipv4"), doc.get("cidr_ipv6"), proto_key="ip_protocol")
    return out


def _fmt_port(rule: tuple) -> str:
    frm, to, proto = rule
    if str(proto) in ("-1", "all"):
        return "ALL traffic"
    return f"{proto}/{frm}" if frm == to else f"{proto}/{frm}-{to}"


def _check_network(rc: ResourceChange):
    newly = _world_open(rc.type, rc.after) - _world_open(rc.type, rc.before)
    flags = []
    for rule in sorted(newly, key=str):
        frm, to = rule[0], rule[1]
        web_only = isinstance(frm, int) and isinstance(to, int) and frm == to and frm in WEB_PORTS
        flags.append(_flag(
            "NETWORK_OPEN_TO_WORLD",
            f"{rc.address}: ingress {_fmt_port(rule)} is newly open to the internet (0.0.0.0/0 or ::/0).",
            "warn" if web_only else "critical",
        ))
    return flags


def _policy_is_public(policy: Any) -> bool:
    try:
        doc = json.loads(policy) if isinstance(policy, str) else policy
    except (ValueError, TypeError):
        return False
    if not isinstance(doc, dict):
        return False
    for stmt in _as_list(doc.get("Statement")):
        if not isinstance(stmt, dict) or stmt.get("Effect") != "Allow" or stmt.get("Condition"):
            continue
        principal = stmt.get("Principal")
        if principal == "*" or (isinstance(principal, dict) and "*" in _as_list(principal.get("AWS"))):
            return True
    return False


def _check_s3(rc: ResourceChange):
    after, before = rc.after or {}, rc.before or {}
    flags = []
    if rc.type == "aws_s3_bucket_public_access_block":
        off = [k for k in PAB_FLAGS if after.get(k) is False and before.get(k) is not False]
        if off:
            flags.append(_flag("S3_PUBLIC_ACCESS_LOOSENED",
                               f"{rc.address}: public access protection turned off ({', '.join(off)}).", "critical"))
    elif rc.type in ("aws_s3_bucket_acl", "aws_s3_bucket"):
        acl = after.get("acl")
        if acl in PUBLIC_ACLS and before.get("acl") != acl:
            flags.append(_flag("S3_PUBLIC_ACCESS_LOOSENED",
                               f"{rc.address}: ACL set to '{acl}'.", "critical"))
    elif rc.type == "aws_s3_bucket_policy":
        if _policy_is_public(after.get("policy")) and not _policy_is_public(before.get("policy")):
            flags.append(_flag("S3_PUBLIC_ACCESS_LOOSENED",
                               f"{rc.address}: bucket policy grants access to Principal \"*\" with no condition.", "critical"))
    return flags


def _check_db(rc: ResourceChange):
    if rc.type in ("aws_db_instance", "aws_rds_cluster_instance"):
        if (rc.after or {}).get("publicly_accessible") is True and (rc.before or {}).get("publicly_accessible") is not True:
            return [_flag("DB_PUBLICLY_ACCESSIBLE",
                          f"{rc.address}: database is now publicly accessible.", "critical")]
    return []


def _check_encryption(rc: ResourceChange):
    key = {"aws_db_instance": "storage_encrypted", "aws_ebs_volume": "encrypted",
           "aws_rds_cluster": "storage_encrypted"}.get(rc.type)
    if key and (rc.after or {}).get(key) is False and (rc.before or {}).get(key) is not False:
        return [_flag("ENCRYPTION_DISABLED", f"{rc.address}: {key} is false.", "critical")]
    return []


def check_security_loosening(changes: list[ResourceChange]) -> list:
    """Run all detectors. Returns a list of RiskFlag; empty means nothing found."""
    flags = []
    for rc in changes:
        if rc.is_delete or rc.is_noop or rc.after is None:
            continue
        for check in (_check_network, _check_s3, _check_db, _check_encryption):
            flags.extend(check(rc))
    return flags
