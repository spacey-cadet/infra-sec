"""terraform_plan_parse

Parses `terraform show -json tfplan.binary` output into a normalized list of
resource changes. This works off Terraform's structured JSON plan format
(not scraped stdout), so it's stable across TF versions that share the same
plan schema version.

Reference: https://developer.hashicorp.com/terraform/internals/json-format
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional
import json

# Resource type prefixes we always care about for IAM/OIDC risk detection.
IAM_TYPE_PREFIXES = (
    "aws_iam_role",
    "aws_iam_policy",
    "aws_iam_role_policy",
    "aws_iam_role_policy_attachment",
    "aws_iam_openid_connect_provider",
    "aws_iam_user",
    "aws_iam_group",
)

DESTRUCTIVE_ACTIONS = {"delete", "replace"}


@dataclass
class ResourceChange:
    address: str
    type: str
    name: str
    actions: list[str]           # e.g. ["update"], ["create"], ["delete", "create"] (replace)
    before: Optional[dict[str, Any]]
    after: Optional[dict[str, Any]]
    provider_name: str = ""

    @property
    def is_replace(self) -> bool:
        return set(self.actions) >= {"delete", "create"}

    @property
    def is_create(self) -> bool:
        return self.actions == ["create"]

    @property
    def is_delete(self) -> bool:
        return self.actions == ["delete"]

    @property
    def is_noop(self) -> bool:
        return self.actions == ["no-op"] or self.actions == []

    @property
    def is_iam_related(self) -> bool:
        return self.type.startswith(IAM_TYPE_PREFIXES)

    @property
    def is_oidc_provider(self) -> bool:
        return self.type == "aws_iam_openid_connect_provider"

    @property
    def has_trust_policy(self) -> bool:
        """True if this resource carries an assume_role_policy document."""
        for doc in (self.before, self.after):
            if doc and "assume_role_policy" in doc:
                return True
        return False


@dataclass
class ParsedPlan:
    resource_changes: list[ResourceChange] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    parse_ok: bool = True
    parse_error: Optional[str] = None

    @property
    def new_resource_types(self) -> set[str]:
        return {rc.type for rc in self.resource_changes if rc.is_create}

    @property
    def touched_iam(self) -> list[ResourceChange]:
        return [rc for rc in self.resource_changes if rc.is_iam_related]

    @property
    def has_unknown_action(self) -> bool:
        known = {"no-op", "create", "read", "update", "delete"}
        for rc in self.resource_changes:
            if not set(rc.actions) <= known:
                return True
        return False


def parse_plan_json(raw_json) -> ParsedPlan:
    """
    Parses raw `terraform show -json` output.
    Fails closed: if the JSON doesn't parse, or the expected top-level
    structure is missing, returns ParsedPlan(parse_ok=False, ...) rather
    than raising, so the caller (decision_engine) can route to a hold.
    """
    try:
        data = json.loads(raw_json) if isinstance(raw_json, (str, bytes)) else raw_json
    except (json.JSONDecodeError, TypeError) as e:
        return ParsedPlan(parse_ok=False, parse_error=f"invalid JSON: {e}")

    if not isinstance(data, dict) or "resource_changes" not in data:
        return ParsedPlan(
            parse_ok=False,
            parse_error="missing 'resource_changes' key, so this isn't a valid terraform plan JSON",
        )

    changes = []
    try:
        for rc in data.get("resource_changes", []) or []:
            change = rc.get("change", {}) or {}
            actions = change.get("actions", []) or []
            changes.append(
                ResourceChange(
                    address=rc.get("address", "<unknown>"),
                    type=rc.get("type", "<unknown>"),
                    name=rc.get("name", "<unknown>"),
                    actions=actions,
                    before=change.get("before"),
                    after=change.get("after"),
                    provider_name=rc.get("provider_name", ""),
                )
            )
    except (AttributeError, TypeError) as e:
        return ParsedPlan(parse_ok=False, parse_error=f"malformed resource_changes entry: {e}")

    return ParsedPlan(resource_changes=changes, raw=data, parse_ok=True)
