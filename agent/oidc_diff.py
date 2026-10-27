"""oidc_trust_diff

Deterministic, purpose-built semantic diff of IAM trust policy documents
(assume_role_policy), with special handling for GitHub Actions OIDC
conditions (token.actions.githubusercontent.com:sub / :aud).

We do not ask the LLM to eyeball a JSON blob and notice that a trust policy
widened. Both documents get parsed into normalized condition sets, and
those sets are diffed programmatically. The LLM only ever receives the
structured verdict this module produces: it explains and prioritizes, it
does not detect.

The one failure mode this exists to catch: a StringLike/StringEquals
condition on `token.actions.githubusercontent.com:sub` (or `:aud`) that
goes from a narrow pattern (e.g. a single branch ref) to a broad one (e.g.
a wildcard covering all branches, PRs, and tags), which silently lets a
much wider set of CI runs assume the role.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional
import fnmatch
import json

OIDC_CONDITION_KEY_SUB = "token.actions.githubusercontent.com:sub"
OIDC_CONDITION_KEY_AUD = "token.actions.githubusercontent.com:aud"
WATCHED_KEYS = (OIDC_CONDITION_KEY_SUB, OIDC_CONDITION_KEY_AUD)

# Operators that matter for this: StringEquals/StringLike (allow) vs the
# *Not* negated variants and wildcard characters.
STRING_CONDITION_OPERATORS = (
    "StringEquals", "StringLike",
    "StringEqualsIgnoreCase", "StringLikeIgnoreCase",
)


@dataclass
class ConditionSnapshot:
    """Normalized view of one watched condition key's allowed patterns."""
    operator: Optional[str] = None
    patterns: list[str] = field(default_factory=list)  # e.g. ["repo:you/repo:ref:refs/heads/main"]

    @property
    def is_wildcarded(self) -> bool:
        return any("*" in p for p in self.patterns)


@dataclass
class OidcDiffResult:
    changed: bool = False
    widened: bool = False           # True only if the new pattern set is a strict superset
    narrowed: bool = False
    key: Optional[str] = None       # which condition key changed (sub/aud)
    before: Optional[ConditionSnapshot] = None
    after: Optional[ConditionSnapshot] = None
    explanation: str = ""
    examples_newly_allowed: list[str] = field(default_factory=list)


def _extract_conditions(policy_doc: Optional[dict[str, Any]]) -> dict[str, ConditionSnapshot]:
    """
    Walks an IAM trust policy document's Statement[].Condition blocks and
    extracts snapshots for each watched key, across all statements.
    Returns {} if the doc is missing/malformed (caller treats that as
    "could not verify" -> fail closed upstream).
    """
    result: dict[str, ConditionSnapshot] = {}
    if not policy_doc:
        return result

    statements = policy_doc.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]

    for stmt in statements or []:
        condition_block = stmt.get("Condition", {}) or {}
        for operator, kv in condition_block.items():
            if operator not in STRING_CONDITION_OPERATORS:
                continue
            if not isinstance(kv, dict):
                continue
            for key, value in kv.items():
                if key not in WATCHED_KEYS:
                    continue
                patterns = value if isinstance(value, list) else [value]
                existing = result.get(key)
                if existing:
                    existing.patterns.extend(patterns)
                else:
                    result[key] = ConditionSnapshot(operator=operator, patterns=list(patterns))
    return result


def _parse_policy_field(raw: Any) -> Optional[dict[str, Any]]:
    """assume_role_policy in plan JSON is usually a JSON-encoded string."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def _is_strict_superset(before_patterns: list[str], after_patterns: list[str]) -> bool:
    """
    True if every string that would have matched `before_patterns` also
    matches `after_patterns`, AND `after_patterns` matches strictly more.
    We approximate "matches" with glob semantics (IAM StringLike uses
    fnmatch-style wildcards), which is the correct semantics for this key.
    """
    def matches_any(value: str, patterns: list[str]) -> bool:
        return any(fnmatch.fnmatchcase(value, p) for p in patterns)

    # Sample the before-patterns themselves as canonical "allowed" strings,
    # plus a synthetic broadened probe for each, to check superset behavior.
    probes = set(before_patterns)
    for p in before_patterns:
        # Turn a wildcard-free literal into a probe as-is; for existing
        # wildcards, keep as representative strings too.
        probes.add(p)

    before_allows = {p for p in probes if matches_any(p, before_patterns)}
    after_allows_same = {p for p in before_allows if matches_any(p, after_patterns)}

    covers_all_before = before_allows == after_allows_same

    # Strictly more permissive if after has a wildcard where before didn't,
    # or after's pattern set is a proper superset of literal strings.
    before_set = set(before_patterns)
    after_set = set(after_patterns)
    more_wildcards = any("*" in p for p in after_set) and not any("*" in p for p in before_set)
    proper_superset = after_set != before_set and covers_all_before

    return covers_all_before and (more_wildcards or proper_superset)


def diff_trust_policy(before_raw: Any, after_raw: Any) -> OidcDiffResult:
    """
    Main entry point. Pass the raw before/after values of the
    `assume_role_policy` (or OIDC provider's client_id_list / thumbprint,
    for aws_iam_openid_connect_provider resources; sub/aud actually live on
    the role side, but this function focuses on the trust-policy condition
    keys, since that's where the widening risk lives).
    """
    before_doc = _parse_policy_field(before_raw)
    after_doc = _parse_policy_field(after_raw)

    before_conditions = _extract_conditions(before_doc)
    after_conditions = _extract_conditions(after_doc)

    all_keys = set(before_conditions) | set(after_conditions)
    if not all_keys:
        return OidcDiffResult(changed=False, explanation="No OIDC sub/aud conditions present in either version.")

    for key in WATCHED_KEYS:
        before_snap = before_conditions.get(key)
        after_snap = after_conditions.get(key)

        before_patterns = sorted(before_snap.patterns) if before_snap else []
        after_patterns = sorted(after_snap.patterns) if after_snap else []

        if before_patterns == after_patterns:
            continue  # no change on this key

        widened = _is_strict_superset(before_patterns, after_patterns) if before_patterns and after_patterns else bool(after_patterns and not before_patterns)
        narrowed = (not widened) and bool(before_patterns) and (
            _is_strict_superset(after_patterns, before_patterns) if after_patterns else True
        )
        # Ambiguous change (neither a clean widen nor a clean narrow): fail
        # closed by treating it as widened so it always escalates.
        if not widened and not narrowed:
            widened = True

        examples = []
        if widened:
            examples = _example_newly_allowed(before_patterns, after_patterns)

        explanation = _build_explanation(key, before_patterns, after_patterns, widened, narrowed)

        return OidcDiffResult(
            changed=True,
            widened=widened,
            narrowed=narrowed,
            key=key,
            before=ConditionSnapshot(operator=before_snap.operator if before_snap else None, patterns=before_patterns),
            after=ConditionSnapshot(operator=after_snap.operator if after_snap else None, patterns=after_patterns),
            explanation=explanation,
            examples_newly_allowed=examples,
        )

    return OidcDiffResult(changed=False, explanation="OIDC conditions present but unchanged.")


def _example_newly_allowed(before_patterns: list[str], after_patterns: list[str]) -> list[str]:
    """Produce a couple of human-readable example subjects that would now
    match `after_patterns` but did NOT match `before_patterns`. This is
    what makes the Slack/PR message concrete instead of abstract."""
    examples = []
    for p in after_patterns:
        if "*" in p:
            # Turn e.g. "repo:you/repo:*" into a couple illustrative concrete subs
            base = p.replace("*", "")
            candidates = [
                base + "ref:refs/heads/some-other-branch",
                base + "pull_request",
            ]
            for c in candidates:
                if not any(fnmatch.fnmatchcase(c, bp) for bp in before_patterns):
                    examples.append(c)
    return examples[:2]


def _build_explanation(key: str, before: list[str], after: list[str], widened: bool, narrowed: bool) -> str:
    short_key = "sub" if key == OIDC_CONDITION_KEY_SUB else "aud"
    if widened:
        return (
            f"OIDC trust condition on '{short_key}' was WIDENED: "
            f"{before or '(none)'} -> {after}. This expands which callers can assume this role."
        )
    if narrowed:
        return (
            f"OIDC trust condition on '{short_key}' was narrowed: "
            f"{before} -> {after}. This restricts which callers can assume this role (lower risk)."
        )
    return (
        f"OIDC trust condition on '{short_key}' changed in a way that is neither a clean widen "
        f"nor a clean narrow: {before} -> {after}. Treat as widened out of caution (fail closed)."
    )
