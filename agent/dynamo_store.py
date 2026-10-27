"""dynamo_decision_log

Read/write past decisions and human overrides to DynamoDB.

Table schema (see terraform/dynamodb.tf):
  PK: repo#plan_id     (string, e.g. "you/repo#a1b2c3")
  SK: timestamp        (string, ISO8601)
  attributes:
    decision            (S) "auto_apply" | "hold"
    risk_flags          (L) list of {code, message, severity}
    cost_delta_usd       (N)
    oidc_diff            (M, nullable)
    human_override       (M, nullable, set later via a separate update)
    confidence           (N)
    resource_types_seen  (SS, used to compute the "new resource type" check)
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import os

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ.get("GUARDIAN_TABLE_NAME", "terraform-guardian-decisions")


def _table():
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(TABLE_NAME)


@dataclass
class DecisionRecord:
    repo: str
    plan_id: str
    timestamp: str
    decision: str
    risk_flags: list
    cost_delta_usd: float
    confidence: float
    oidc_diff: Optional[dict] = None
    human_override: Optional[dict] = None
    resource_types_seen: Optional[list] = None


def put_decision(record: DecisionRecord) -> None:
    item = {
        "pk": f"{record.repo}#{record.plan_id}",
        "sk": record.timestamp,
        "decision": record.decision,
        "risk_flags": record.risk_flags,
        "cost_delta_usd": str(record.cost_delta_usd),
        "confidence": str(record.confidence),
    }
    if record.oidc_diff is not None:
        item["oidc_diff"] = record.oidc_diff
    if record.human_override is not None:
        item["human_override"] = record.human_override
    if record.resource_types_seen is not None:
        item["resource_types_seen"] = list(set(record.resource_types_seen)) or ["__none__"]

    _table().put_item(Item=item)


def get_known_resource_types(repo: str, lookback: int = 200) -> set[str]:
    """Scans recent decisions for this repo and unions their
    resource_types_seen sets, to support the 'new resource type' escalation
    rule. A GSI on `repo` would be more efficient at scale; for a hackathon,
    a query against the repo's partition prefix is good enough."""
    table = _table()
    known: set[str] = set()
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").begins_with(f"{repo}#"),
            Limit=lookback,
            ScanIndexForward=False,
        )
        for item in resp.get("Items", []):
            for t in item.get("resource_types_seen", []) or []:
                if t != "__none__":
                    known.add(t)
    except Exception:
        # Fail closed on read errors too: an empty known-types set means
        # everything in this plan looks "new," which routes to hold. That's
        # the safer direction to fail in.
        return set()
    return known


def record_human_override(repo: str, plan_id: str, timestamp: str, override: dict) -> None:
    """Called from a separate approval webhook/Lambda when a human approves
    a held plan or flags a bad auto-apply after the fact. This is the
    feedback-loop signal referenced in the README."""
    _table().update_item(
        Key={"pk": f"{repo}#{plan_id}", "sk": timestamp},
        UpdateExpression="SET human_override = :ho",
        ExpressionAttributeValues={":ho": override},
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
