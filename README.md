# InfraSec

**Agents that decide which infrastructure changes are safe to ship, and which need a human.**

InfraSec reads a Terraform plan and returns a deterministic verdict: `auto_apply` or `hold`.
When it holds a change, a GitLab Duo agent explains why, commits the fix, and re-runs the
pipeline. It also reads your repo and suggests the infrastructure code it needs (least-privilege
IAM, a pinned OIDC trust, environment and package fixes).

> Built for the GitLab Transcend hackathon: **Path B** (Bring Your Own), **Hands-off** autonomy.
> Formerly "Infra Risk"; the Python package and CLI keep the `infra-risk` name.

## Why

AI can write infrastructure code in seconds, but the review after it is still manual. The
changes that hurt most are the ones that look fine to CI: a security group opened to the
internet, an S3 public-access block switched off, an OIDC trust condition widened to
`repo:org/repo:*`. They are valid Terraform, `validate` and `apply` accept them, and a normal
pipeline ships them.

**The rule we hold to: the AI explains and fixes, but never decides.** Every verdict comes from
plain, tested Python. An LLM can never flip `hold` to `auto_apply`.

## How it works

```
push ──> plan ──> conventional CI (fmt / validate / tests)
                          │
                          v
                InfraSec gate (deterministic)
              ┌───────────┴────────────┐
           PASS                      HELD (pipeline fails)
              │                         │
     deploy staging -> prod    Duo flow fires on "pipeline failed":
     (default branch)           1. explains why it did not pass
                                2. commits the minimal fix  [infrasec-autofix]
                                3. posts /merge: merges only if the re-run passes
                                4. after 2 attempts, or for findings it must not
                                   fix, labels infrasec::needs-human and stops
```

The report states what normal CI said, so it is honest about InfraSec's role:

| CI said | InfraSec said | Value added |
|---|---|---|
| pass | held | **Gate.** CI alone would have shipped it. |
| fail | held | **Diagnosis.** CI was failing anyway; InfraSec only explains and proposes a fix. |
| pass | pass | None. |

## What it checks

The decision engine is an OR-gate: any single finding holds the plan. It fails closed.

| Code | Catches | Agent may auto-fix |
|---|---|---|
| `OIDC_TRUST_WIDENED` | GitHub OIDC trust condition loosened | yes (re-pin `sub`) |
| `NETWORK_OPEN_TO_WORLD` | new ingress from `0.0.0.0/0` or `::/0` | yes |
| `S3_PUBLIC_ACCESS_LOOSENED` | public-access-block off, public ACL, `Principal: "*"` policy | yes |
| `DB_PUBLICLY_ACCESSIBLE` | RDS made public | yes |
| `ENCRYPTION_DISABLED` | storage or volume encryption turned off | yes |
| `IAM_RESOURCE_TOUCHED` | any IAM or policy resource | no, human review |
| `NEW_RESOURCE_TYPE` | first use of a resource type in this repo | no, human review |
| `COST_THRESHOLD_EXCEEDED` | increase of $2/month or more, or 40% of baseline | no, human review |
| `PARSE_ERROR`, `UNKNOWN_ACTION` | plan cannot be read safely | no, human review |

Findings the agent must not fix (IAM, cost, new resource types, parse errors) always go to a human.

## Suggest: generate the right infra code

```bash
python scripts/infrasec_suggest.py --root . --repo ORG/REPO    # writes suggested-infra/*.tf and a report
```

| It detects | It suggests |
|---|---|
| boto3 and `@aws-sdk` calls (with file:line evidence) | Least-privilege IAM policy. Resources are variables, never `"*"` |
| CI that uses `role-to-assume` or `id_tokens` | An OIDC role trusted for one repo and branch (`StringEquals`, no wildcard) |
| `role-to-assume` without `permissions: id-token: write` | A critical finding with the fix |
| AWS SDK used but not declared in requirements or package.json | The missing package |
| Secret-looking environment variables (`*_TOKEN`, `*_KEY`) | Secrets Manager by ARN, not plain env |
| Services outside the verified list | Marked `check` so a human verifies the derived action |

Suggestions always touch IAM, so the gate holds them for a human. The `infrasec-suggest` flow
opens them as a merge request and never auto-merges.

## Quick start

No AWS account is needed for the demo.

```bash
pip install pytest python-hcl2
python -m pytest tests/ -q                                                       # 40 tests

python scripts/infrasec_decide.py --plan demo/plans/safe.json     --ci-status pass   # exit 0: pass
python scripts/infrasec_decide.py --plan demo/plans/ssh_open.json --ci-status pass   # exit 2: held, value "gate"
python scripts/infrasec_decide.py --plan demo/plans/ssh_open.json --ci-status fail   # exit 3: value "diagnosis"
```

Exit codes: `0` pass, `2` held by InfraSec, `3` conventional CI failed.

## Run it on GitLab

1. Push this repository to a GitLab project. Every push runs `.gitlab-ci.yml`.
2. Enable the flows (Automate > Flows). Paste each file from `flows/` and fix anything the editor flags:
   - `infrasec-autofix.yaml`: set the trigger to **pipeline failed**.
   - `infrasec-suggest.yaml`: mention `@infrasec-suggest` on an issue or merge request.
3. To exercise the gate without Terraform, run a manual pipeline with `DEMO_PLAN=demo/plans/ssh_open.json`.
4. To trigger the full loop, change `cidr_blocks` in `demo-target/main.tf` to `["0.0.0.0/0"]` and push.

Without AWS credentials the deploy jobs print `DEMO MODE` instead of applying.

## The AWS decision API

The original deployment: an IAM-authenticated Lambda Function URL that evaluates plans from any CI.

`POST` JSON with `repo`, `head_sha` and `plan_json`, signed with AWS SigV4. The `infra-risk` client
exits `0` for `auto_apply`, `2` for `hold`, and nonzero on request or credential errors; CI should
treat every nonzero exit as blocked.

For GitHub Actions, copy [`examples/infra-risk.yml`](examples/infra-risk.yml) into
`.github/workflows/`, set the repository variables `INFRA_RISK_CLIENT_ROLE_ARN` and
`INFRA_RISK_API_URL`, and replace the sample Git URL. Details are in [`docs/workflow.md`](docs/workflow.md).

An optional advisory classifier (Fastino GLiNER2.5-Decide) can be attached to the response. It
never changes the verdict. Install it with `pip install 'infra-risk[gliner] @ git+...'` and set
`INFRA_RISK_GLINER_MODEL=fastino/GLiNER2.5-Decide`.

### Deploy

Requires AWS credentials, Terraform 1.5+ and Docker.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars      # set github_org, github_repo, allowed_ref, notification_email
terraform init
terraform apply -target=aws_ecr_repository.guardian          # create the ECR repository first
# build and push the image to the ecr_repository_url output, then:
terraform apply -var="infra_risk_image_uri=<ecr_repository_url>:latest"
```

Outputs: `decision_api_url` and `plan_submitter_role_arn`. Review the IAM trust inputs
(`github_org`, `github_repo`, `allowed_ref`) before deploying. Build the image for `linux/amd64`.

## Repository map

| Path | What it is |
|---|---|
| `agent/` | `plan_parser`, `oidc_diff`, `cost_estimate`, `security_checks`, `decision_engine` (the verdict); `suggest` (infra-code suggester); `handler` (Lambda entry point) |
| `scripts/infrasec_decide.py` | Offline gate used by the GitLab pipeline |
| `scripts/infrasec_suggest.py` | Infra-code suggester CLI |
| `flows/` | GitLab Duo flows: auto-fix and suggest |
| `.gitlab-ci.yml` | Hands-off pipeline: plan, CI, gate, deploy |
| `demo-target/`, `demo/plans/` | The infrastructure the demo guards, and saved plans |
| `infra_risk/` | Small installable CI client (`infra-risk` command) |
| `terraform/` | Lambda, OIDC access, decision history and notifications |
| `docs/` | `INFRASEC.md`, `decision_engine.md`, `workflow.md` |
| `tests/` | 40 tests: parser, OIDC diff, decision matrix, security checks, suggester |

## GitLab lifecycle stages

| Stage | What happens |
|---|---|
| Plan | The agent posts its explanation on the merge request |
| Create | The agent commits the fix to the branch |
| Verify | `terraform fmt`, `validate` and the test suite run |
| Secure | The security gate decides pass or hold |
| Release | The default branch deploys to staging, then production, with no human |
| Govern | Every push records the decision, the reasoning and what CI said |

## Status and limits

| Verified | Not yet verified |
|---|---|
| Decision engine, security checks and suggester: 40 passing tests | `.gitlab-ci.yml` end to end on GitLab |
| Generated Terraform parses as HCL | Generated Terraform through `terraform validate` |
| The gate and CLI on the demo plans | The Duo flows (tool names are drafts, adjust them in the flow editor) |

- The suggester understands AWS SDK calls in Python and JS/TS, GitHub and GitLab CI, and emits Terraform. Calls made through helper wrappers can be missed.
- The GitLab pipeline keeps known resource types in `.infrasec/known_types.json`; the AWS Lambda keeps them in DynamoDB.
- The Lambda does not run `terraform apply` itself; applying is a separate pipeline job.

## License

MIT