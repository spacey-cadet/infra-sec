# Decision Engine: Cost Matrix & Escalation Logic

`decision_engine.evaluate()` is a deterministic, ordered cascade of checks over a parsed Terraform plan. Any check that trips returns `hold` immediately — later checks in the list don't run. If nothing trips, the plan auto-applies. An optional LLM can explain a decision afterward but cannot change it.

## Cost matrix

| Signal | Threshold | Result if exceeded |
|---|---|---|
| Absolute monthly delta | `$2.00/mo` | hold |
| Relative monthly delta | `40%` of baseline monthly cost | hold |

Either condition alone is enough — it's an OR, not an AND. A plan that adds $1.50/mo but doubles a near-zero baseline can still hold on the percentage leg; a plan that adds $50/mo to a $2,000/mo baseline can still hold on the absolute leg even though it's a small percentage.

Cost is checked *after* IAM/OIDC checks. A plan with a clean cost delta can still hold on a trust-policy or IAM signal, and a plan with an expensive cost delta never gets there if OIDC or IAM already forced a hold — the cost check simply never runs.

## Decision order

The cascade runs in this order. First trip wins.

1. **Plan failed to parse** → hold (confidence 1.0)
   Fails closed on any parse error, before any content is evaluated.

2. **OIDC trust policy widened** → hold (confidence 0.98)
   Checked against every resource with a trust policy or that's an OIDC provider, diffing `assume_role_policy` before/after. This is the single highest-priority signal — it overrides cost, resource type, everything. Marked `highest_priority: true` in the output.

3. **Any IAM/policy resource touched** → hold (confidence 0.95)
   Doesn't require the trust policy to have widened — just touching an IAM/policy-type resource at all (create, update, or delete) is enough.

4. **New-to-repo resource type** → hold (confidence 0.85)
   Compared against `known_resource_types`, sourced from that repo's DynamoDB plan history. First time a repo has seen a given resource type, it holds for a first-look review — lower confidence because unfamiliar isn't inherently dangerous.

5. **Cost threshold exceeded** → hold (confidence 0.9)
   The cost matrix above.

6. **Nothing tripped** → `auto_apply` (confidence 0.97)
   Non-sensitive resource replacements (destroy+create on something that isn't IAM/OIDC) still get logged as `info`-level flags for visibility but don't block the apply.

## How it diffs a change

Diffing happens at two different levels, and only one of them is a real semantic diff.

**Plan-level diff — already done by Terraform.** `terraform show -json` carries a `before` and `after` attribute snapshot for every changed resource. `plan_parser.py` reads that into `ResourceChange.before` / `.after`. Guardian doesn't diff two live infrastructure states itself — it consumes the diff Terraform already computed and extracts the fields it needs (resource type, action, whether it has a trust policy, and so on).

**OIDC trust-policy diff — Guardian's own semantic diff.** For any resource where `has_trust_policy` or `is_oidc_provider` is true, `decision_engine.py` pulls `before["assume_role_policy"]` and `after["assume_role_policy"]` and passes both to `diff_trust_policy()` in `oidc_diff.py`. It returns:

- `changed` — whether the policy differs at all
- `widened` — whether it got more permissive, not just different
- `before.patterns` / `after.patterns` — the condition patterns (e.g. which repos/branches/subjects can assume the role) parsed out of each policy version
- `examples_newly_allowed` — concrete identities that could assume the role after the change but couldn't before

`widened` can't come from a plain string or JSON compare — two policies can differ syntactically while permitting the exact same callers, or differ by one character and permit a strictly larger set. The `examples_newly_allowed` field only makes sense if the diff is comparing the *set of allowed callers* implied by each policy's condition block (for GitHub OIDC, typically the `token.actions.githubusercontent.com:sub` claim pattern), not the raw JSON.

**Everything else is cheaper than a diff.**
- New-resource-type check: a plain set difference, `parsed_plan.new_resource_types - known_resource_types` — comparing type *names*, not configurations.
- IAM-touched check: resource type category plus the plan's `actions` list (create/update/delete) — it doesn't inspect what the permission change actually does.
- Cost check: not a diff of the plan at all. `CostEstimateResult.delta_usd` compares an estimated baseline against the post-change estimate, computed separately from plan parsing.

So real semantic diffing — does this specific change expand who can do what — only happens for OIDC trust policies, and only inside `oidc_diff.py`.

## Notes

- **Confidence is informational, not a gate.** Nothing in `evaluate()` reads confidence back to change the action. It's there for the reviewer (or the downstream LLM explanation) to weigh, not for the engine to weigh against itself.
- **Not a pure parallel OR-gate.** Functionally, any single signal can force a hold, matching the "OR-gate" design intent — but the checks run in a fixed priority order and return on first hit. A plan that fails on both IAM and cost only ever reports the IAM hold; the cost check never executes.
- **Unknown resource actions** (outside create/read/update/delete/no-op) get flagged critical but don't force an immediate return — they ride along with whatever the final decision ends up being.