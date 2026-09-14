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

## Notes

- **Confidence is informational, not a gate.** Nothing in `evaluate()` reads confidence back to change the action. It's there for the reviewer (or the downstream LLM explanation) to weigh, not for the engine to weigh against itself.
- **Not a pure parallel OR-gate.** Functionally, any single signal can force a hold, matching the "OR-gate" design intent — but the checks run in a fixed priority order and return on first hit. A plan that fails on both IAM and cost only ever reports the IAM hold; the cost check never executes.
- **Unknown resource actions** (outside create/read/update/delete/no-op) get flagged critical but don't force an immediate return — they ride along with whatever the final decision ends up being.