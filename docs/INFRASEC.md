# InfraSec: hands-off infrastructure security gate on GitLab

Built on Infra Risk Guardian (deterministic decision engine) for the GitLab Transcend
hackathon, **Path B (Bring Your Own)**, **Hands-off** autonomy.

## The loop

```
push ──> pipeline ──> plan ──> conventional CI (fmt / validate / tests)
                                   │
                                   v
                          InfraSec gate (deterministic)
                     ┌─────────────┴──────────────┐
                  PASS                          HELD (pipeline fails)
                     │                              │
        deploy staging -> production      Duo flow fires on "pipeline failed"
        (default branch, no human)         1. explains why it did not pass
                                           2. commits the minimal fix [infrasec-autofix]
                                           3. posts /merge (merges only if the re-run passes)
                                           4. after 2 attempts, or for non-fixable findings,
                                              labels infrasec::needs-human and stops
```

Nobody approves anything on the happy path or the fix path. A human is pulled in only
when the agent cannot fix safely (IAM changes, new resource types, cost, parse errors).

## Why the agent is not redundant with CI

`infrasec-report.md` records what conventional CI said and states the value added:

| CI said | InfraSec said | Value added |
|---|---|---|
| pass | held | **gate**: CI alone would have shipped it (valid Terraform that loosens security) |
| fail | held | **diagnosis**: CI was failing anyway; InfraSec only explains and proposes the fix |
| pass | pass | none |

The demo should use changes in the first row. Examples that `terraform validate`, `plan`
and `apply` all accept: a security group opened to `0.0.0.0/0`, an S3 public-access
block switched off, a database made public, encryption disabled, an OIDC trust `sub`
widened to `repo:org/repo:*`.

## What InfraSec checks (all deterministic; the LLM never changes a verdict)

| Code | Catches | Agent auto-fix |
|---|---|---|
| `OIDC_TRUST_WIDENED` | GitHub OIDC trust condition loosened | yes (re-pin `sub`) |
| `NETWORK_OPEN_TO_WORLD` | new ingress from 0.0.0.0/0 or ::/0 | yes |
| `S3_PUBLIC_ACCESS_LOOSENED` | public-access-block off, public ACL, `Principal: "*"` policy | yes |
| `DB_PUBLICLY_ACCESSIBLE` | RDS made public | yes |
| `ENCRYPTION_DISABLED` | storage/volume encryption turned off | yes |
| `IAM_RESOURCE_TOUCHED` | any IAM/policy resource | no, needs a human |
| `NEW_RESOURCE_TYPE` | first use of a resource type | no, needs a human |
| `COST_THRESHOLD_EXCEEDED` | >= $2/mo or 40% of baseline | no, needs a human |
| `PARSE_ERROR` / `UNKNOWN_ACTION` | fails closed | no, needs a human |

## Suggest: generate the right infra code, then verify it

InfraSec also reads your repo and suggests the infrastructure it needs, so the first deploy
does not fail on IAM / OIDC trial and error. It is deterministic; the Duo agent reviews it.

```bash
python scripts/infrasec_suggest.py --root . --repo ORG/REPO    # writes suggested-infra/*.tf + report
```

| Detects | Suggests |
|---|---|
| boto3 / `@aws-sdk` calls (file:line evidence) | Least-privilege IAM policy. Actions derived from the calls, resources as variables, never `"*"` |
| CI uses `role-to-assume` / `id_tokens` | OIDC role trusted for ONE repo + branch (`StringEquals`, no wildcard) |
| `role-to-assume` without `permissions: id-token: write` | The classic silent failure, flagged as critical with the fix |
| AWS SDK used but not in requirements / package.json | Add the missing package |
| Secret-looking env vars (`*_TOKEN`, `*_KEY`, ...) | Route to Secrets Manager by ARN, not plain env |
| Services not on the verified list | Marked `check` so a human verifies the derived action |

Generate, then verify: suggestions always touch IAM, so the gate holds them for a human
(by design). The `infrasec-suggest` flow opens them as a merge request and never auto-merges.

## Lifecycle stages touched

Plan (agent note), Create (agent commit), Verify (fmt/validate/tests), Secure (security
gate), Release (auto deploy), Govern (decision + reasoning recorded per push),
Package and Monitor only if you add real jobs for them. Claim only what appears in your
pipeline history.

## Run it

```bash
pip install pytest python-hcl2 && python -m pytest tests/ -q       # 40 tests, no AWS needed
python scripts/infrasec_decide.py --plan demo/plans/safe.json      --ci-status pass   # exit 0
python scripts/infrasec_decide.py --plan demo/plans/ssh_open.json  --ci-status pass   # exit 2, value: gate
python scripts/infrasec_decide.py --plan demo/plans/ssh_open.json  --ci-status fail   # exit 3, value: diagnosis
```

In GitLab: push this repo, enable `flows/infrasec-autofix.yaml` (Automate > Flows) with the
"pipeline failed" trigger, then push a change to `demo-target/main.tf` that sets the
security group's `cidr_blocks` to `["0.0.0.0/0"]`.

## Honest limits

- The flow YAML and its toolset names are unverified against a live GitLab instance.
- Terraform is not installed in the authoring sandbox: `.gitlab-ci.yml` and the offline
  `terraform plan` in `demo-target/` have not been run end to end. Set `DEMO_PLAN=demo/plans/ssh_open.json`
  on a manual pipeline to exercise the gate without Terraform.
- Without AWS credentials the deploy jobs print "DEMO MODE" instead of applying.
- The suggester only knows AWS SDK calls in Python and JS/TS, GitHub and GitLab CI, and Terraform output. Actions on services outside its verified list are derived from method names and marked `check`. Generated Terraform parses (tested) but was not run through `terraform validate`.
- Known-resource-type history is a committed file (`.infrasec/known_types.json`) in the
  GitLab pipeline; the AWS Lambda deployment keeps it in DynamoDB.
