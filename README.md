<<<<<<< HEAD
# infrasec



## Getting started

To make it easy for you to get started with GitLab, here's a list of recommended next steps.

Already a pro? Just edit this README.md and make it your own. Want to make it easy? [Use the template at the bottom](#editing-this-readme)!

## Add your files

* [Create](https://docs.gitlab.com/user/project/repository/web_editor/#create-a-file) or [upload](https://docs.gitlab.com/user/project/repository/web_editor/#upload-a-file) files
* [Add files using the command line](https://docs.gitlab.com/topics/git/add_files/#add-files-to-a-git-repository) or push an existing Git repository with the following command:

```
cd existing_repo
git remote add origin https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43740873/infrasec.git
git branch -M main
git push -uf origin main
```

## Integrate with your tools

* [Set up project integrations](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43740873/infrasec/-/settings/integrations)

## Collaborate with your team

* [Invite team members and collaborators](https://docs.gitlab.com/user/project/members/)
* [Create a new merge request](https://docs.gitlab.com/user/project/merge_requests/creating_merge_requests/)
* [Automatically close issues from merge requests](https://docs.gitlab.com/user/project/issues/managing_issues/#closing-issues-automatically)
* [Enable merge request approvals](https://docs.gitlab.com/user/project/merge_requests/approvals/)
* [Set auto-merge](https://docs.gitlab.com/user/project/merge_requests/auto_merge/)

## Test and Deploy

Use the built-in continuous integration in GitLab.

* [Get started with GitLab CI/CD](https://docs.gitlab.com/ci/quick_start/)
* [Analyze your code for known vulnerabilities with Static Application Security Testing (SAST)](https://docs.gitlab.com/user/application_security/sast/)
* [Deploy to Kubernetes, Amazon EC2, or Amazon ECS using Auto Deploy](https://docs.gitlab.com/topics/autodevops/requirements/)
* [Use pull-based deployments for improved Kubernetes management](https://docs.gitlab.com/user/clusters/agent/)
* [Set up protected environments](https://docs.gitlab.com/ci/environments/protected_environments/)

***

# Editing this README

When you're ready to make this README your own, just edit this file and use the handy template below (or feel free to structure it however you want - this is just a starting point!). Thanks to [makeareadme.com](https://www.makeareadme.com/) for this template.

## Suggestions for a good README

Every project is different, so consider which of these sections apply to yours. The sections used in the template are suggestions for most open source projects. Also keep in mind that while a README can be too long and detailed, too long is better than too short. If you think your README is too long, consider utilizing another form of documentation rather than cutting out information.

## Name
Choose a self-explaining name for your project.

## Description
Let people know what your project can do specifically. Provide context and add a link to any reference visitors might be unfamiliar with. A list of Features or a Background subsection can also be added here. If there are alternatives to your project, this is a good place to list differentiating factors.

## Badges
On some READMEs, you may see small images that convey metadata, such as whether or not all the tests are passing for the project. You can use Shields to add some to your README. Many services also have instructions for adding a badge.

## Visuals
Depending on what you are making, it can be a good idea to include screenshots or even a video (you'll frequently see GIFs rather than actual videos). Tools like ttygif can help, but check out Asciinema for a more sophisticated method.

## Installation
Within a particular ecosystem, there may be a common way of installing things, such as using Yarn, NuGet, or Homebrew. However, consider the possibility that whoever is reading your README is a novice and would like more guidance. Listing specific steps helps remove ambiguity and gets people to using your project as quickly as possible. If it only runs in a specific context like a particular programming language version or operating system or has dependencies that have to be installed manually, also add a Requirements subsection.

## Usage
Use examples liberally, and show the expected output if you can. It's helpful to have inline the smallest example of usage that you can demonstrate, while providing links to more sophisticated examples if they are too long to reasonably include in the README.

## Support
Tell people where they can go to for help. It can be any combination of an issue tracker, a chat room, an email address, etc.

## Roadmap
If you have ideas for releases in the future, it is a good idea to list them in the README.

## Contributing
State if you are open to contributions and what your requirements are for accepting them.

For people who want to make changes to your project, it's helpful to have some documentation on how to get started. Perhaps there is a script that they should run or some environment variables that they need to set. Make these steps explicit. These instructions could also be useful to your future self.

You can also document commands to lint the code or run tests. These steps help to ensure high code quality and reduce the likelihood that the changes inadvertently break something. Having instructions for running tests is especially helpful if it requires external setup, such as starting a Selenium server for testing in a browser.

## Authors and acknowledgment
Show your appreciation to those who have contributed to the project.

## License
For open source projects, say how it is licensed.

## Project status
If you have run out of energy or time for your project, put a note at the top of the README saying that development has slowed down or stopped completely. Someone may choose to fork your project or volunteer to step in as a maintainer or owner, allowing your project to keep going. You can also make an explicit request for maintainers.
=======
# Infra Cost Guardian

A single-purpose agent that intercepts every `terraform plan`, decides
**auto-apply vs. hold-for-human**, and is provably right about the one thing
that matters most: **never auto-applying a change that silently loosens
security**, especially a widened GitHub Actions OIDC trust condition.

> **TL;DR for judges:** run `python3 -m pytest tests/ -v`. Three fixture
> plans (boring, expensive, and the OIDC-widening trap) all resolve exactly
> as the escalation matrix below says they should, which is the whole claim,
> demonstrated in about two seconds.

---

## Why this, and why an agent instead of a CI rule

A `git diff` that changes

```diff
- "token.actions.githubusercontent.com:sub": "repo:you/repo:ref:refs/heads/main"
+ "token.actions.githubusercontent.com:sub": "repo:you/repo:*"
```

looks like a one-line, low-risk change to a human skimming a PR. It is
actually a change that lets **any branch, PR, or workflow in the repo**
assume a role that was previously restricted to `main`. A generic
"IAM was touched, please review" CI check would catch this, eventually,
if the reviewer reads carefully. This project instead:

1. **Parses Terraform's structured JSON plan** (not scraped `plan` stdout),
   so extraction is reliable across plans.
2. Runs a **deterministic, purpose-built semantic diff** (`agent/oidc_diff.py`)
   over the trust policy's `sub`/`aud` conditions, glob-aware, so it
   understands that `repo:you/repo:*` is a strict superset of
   `repo:you/repo:ref:refs/heads/main`, not just "the string changed."
3. Only **after** that deterministic verdict exists does an LLM layer get
   involved, and its job is to explain and prioritize for the human
   reviewer, never to detect or to override the verdict. See
   `decision_engine.py`'s module docstring for why this split matters: *we
   don't trust the LLM to catch security regressions by vibes; we trust a
   deterministic parser and let the LLM handle judgment and communication.*
4. **Fails closed everywhere.** Unparseable plans, unknown resource
   actions, missing trust-policy data, and even exceptions inside the
   Lambda handler itself all route to `hold`, never to a silent
   auto-apply. See `agent/handler.py`'s outer `try/except`.

---

## The escalation matrix

| Signal in plan | Action | Escalate? |
|---|---|---|
| No resource replacement, no IAM/policy resource types touched, cost delta < $2/mo | Auto-apply | No |
| Resource replacement (`-/+`) on a non-sensitive resource (e.g. Lambda code hash change) | Auto-apply | No |
| Cost delta ≥ $2/mo or ≥ 40% of current spend | Hold | Yes |
| Any diff touching `aws_iam_role`, `aws_iam_policy`, `aws_iam_role_policy`, `aws_iam_openid_connect_provider` | Hold | Yes |
| Diff in an OIDC trust policy `sub`/`aud` condition, even a single-character change | **Hold + special-cased explanation** | **Yes, highest priority** |
| New resource type never seen before in this repo's plan history | Hold | Yes |
| Plan fails to parse cleanly / unknown resource action | Hold (fail closed) | Yes |

This is implemented as a strict **OR-gate** in `agent/decision_engine.py`:
any single check firing routes to hold. There is no scoring or averaging
that could let a critical risk get diluted by a big plan full of boring
changes. Rule order in the code (OIDC → IAM → new-type → cost) determines
*which* flag gets reported first when several fire at once, not whether the
plan holds; any one of them alone is already sufficient to hold.

---

## Architecture

```
GitHub Actions (PR opened)
  └─ assume guardian plan-submitter role via GitHub OIDC
  └─ terraform plan -out=tfplan.binary
  └─ terraform show -json tfplan.binary > plan.json
  └─ upload plan.json → S3 plan bucket
  └─ push {repo, pr_number, head_sha, plan_json_s3_uri} → SQS
                                │
                                ▼
                     SQS queue (terraform-guardian-plan-queue)
                                │
                                ▼
                Lambda (container image, agent/handler.py)
                   └─ Strands Agent wrapper (agent/strands_agent.py)
                      tools:
                      1. terraform_plan_parse     (structured extraction)
                      2. terraform_cost_estimate  (Infracost or heuristic fallback)
                      3. guardian_decision        (escalation matrix, OR-gate, fail-closed)
                                │
                    ┌───────────┴────────────┐
                    ▼                        ▼
              auto_apply                   hold
                    │                        │
          signal CI to run apply       sns_notify (only escalation path)
          under the scoped OIDC        github_client (check run + PR comment)
          apply role (oidc.tf)         dynamo_store (decision + human_override)
                    │
          dynamo_store (decision log)
```

### Why a dedicated `oidc_trust_diff` tool

For the one class of change we most want to never miss, we don't rely on
model attention over a big plan blob. `agent/oidc_diff.py` pulls out
exactly the trust-policy condition block, normalizes it (handles
`StringEquals` vs `StringLike`, single values vs lists), and computes a
strict-superset check using glob semantics, then hands the caller a clean
`{widened: bool, before: [...], after: [...], examples_newly_allowed: [...]}`
verdict. Ambiguous changes (neither a clean widen nor a clean narrow) are
treated as widened, i.e. fail closed.

---

## Repository layout

```
agent/
  plan_parser.py       terraform_plan_parse: structured extraction from `terraform show -json`
  oidc_diff.py         oidc_trust_diff: deterministic semantic diff of sub/aud conditions
  cost_estimate.py     cost_estimate: Infracost wrapper plus offline heuristic fallback
  decision_engine.py   the escalation matrix as plain, testable Python (OR-gate, fail-closed)
  strands_agent.py     Strands Agents SDK wrapper exposing the deterministic review tools
  dynamo_store.py      dynamo_decision_log: decision history plus human_override feedback loop
  notify.py            sns_notify: the single escalation channel (Slack/email via SNS)
  github_client.py     github_api: posts a Check Run and PR comment so reviewers see it in-review
  handler.py           Lambda entry point; SQS-triggered; fails closed on any unhandled exception
Dockerfile, requirements.txt    Lambda container image build
terraform/
  oidc.tf              GitHub Actions OIDC provider plus the scoped apply-role trust policy
                          (the "what good looks like" reference for the demo)
  iam.tf               least-privilege policies for the apply role and the Lambda exec role
  plan_submitter.tf    scoped OIDC role for watched repos to upload plan JSON and send SQS
  dynamodb.tf, sns.tf, sqs.tf, s3.tf, lambda.tf, outputs.tf
  variables.tf, provider.tf, terraform.tfvars.example
examples/terraform-guardian.yml   copy/paste workflow for the watched repo
docs/workflow.md                  end-to-end explanation of the guardian/watched-repo flow
tests/
  fixtures/plan_safe.json          boring Lambda memory bump -> auto_apply
  fixtures/plan_cost.json           new NAT gateway -> hold (cost + new-resource-type)
  fixtures/plan_oidc_trap.json      the key demo scenario: sub claim widened -> hold, highest_priority
  fixtures/plan_malformed.json      invalid JSON -> hold (fail closed)
  test_plan_parser.py, test_oidc_diff.py, test_decision_engine.py
```

---

## Running the tests (no AWS account required)

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -v
# or, without pytest installed:
python3 tests/test_plan_parser.py
python3 tests/test_oidc_diff.py
python3 tests/test_decision_engine.py
python3 tests/test_strands_agent.py
```

All five decision-engine tests and the OIDC-diff tests pass against the
fixtures above, including the exact demo scenario: `plan_oidc_trap.json`
resolves to `action: hold`, `highest_priority: true`, with a structured
`oidc_diff` showing `repo:you/repo:ref:refs/heads/main` →
`repo:you/repo:*` and two concrete "this would newly allow" examples.

You can also run the full Lambda handler locally end-to-end (with
`boto3` calls monkeypatched out); see the smoke-test pattern in this
repo's development history; the handler correctly produces:

```
🔒 Terraform plan HELD -- you/repo, PR #12
Risk: OIDC trust policy widened
  sub: repo:you/repo:ref:refs/heads/main -> repo:you/repo:*
This would newly allow, e.g.: repo:you/repo:ref:refs/heads/some-other-branch; repo:you/repo:pull_request
Cost impact: +$0.00/mo (est.)
[Approve & Apply]  [View full plan]  [Reject]
```

versus the boring case:

```
✅ Terraform plan auto-applied -- you/repo, PR #13
No IAM/security resources touched.
Cost impact: +$0.00/mo (est.)
```

---

## Deploying

### Prerequisites

- An AWS account and credentials configured locally (`aws configure`).
- Terraform ≥ 1.5 installed locally (not available in the sandbox this
  repo was authored in, so **run `terraform validate` and `terraform plan`
  yourself before the first `apply`**. The `.tf` files were hand-checked
  for brace/quote balance and internal consistency but not run through the
  real CLI).
- Docker, for building the Lambda container image.
- A GitHub repo you want the guardian to watch, plus permission to add
  repo variables/secrets and branch protection rules.

### 1. Bootstrap the ECR repository

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: github_org, github_repo, allowed_ref, notification_email

terraform init
terraform apply -target=aws_ecr_repository.guardian
```

### 2. Build and push the Lambda image

```bash
cd ..
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <ecr_repository_url from output>

docker buildx build \
  --platform linux/amd64 \
  --provenance=false \
  --sbom=false \
  -t <ecr_repository_url>:latest \
  --push \
  .
```

### 3. Point Lambda at the pushed image

```bash
cd terraform
terraform apply -var="guardian_image_uri=<ecr_repository_url>:latest"
```

If Lambda rejects the image with
`InvalidParameterValueException: The image manifest, config or layer media type
for the source image is not supported`, rebuild and push it with the exact
`docker buildx build` command above. Lambda requires a single-platform image
manifest for its architecture; multi-architecture indexes and BuildKit
attestation/provenance manifests can trigger this error.

### 4. Wire up the watched repo's GitHub Actions

- Add repo variables (Settings → Secrets and variables → Actions → Variables):
  - `GUARDIAN_PLAN_SUBMITTER_ROLE_ARN` = `plan_submitter_role_arn` output
  - `GUARDIAN_QUEUE_URL` = `plan_queue_url` output
  - `GUARDIAN_PLAN_BUCKET` = `plan_artifacts_bucket` output
- Copy `examples/terraform-guardian.yml` into the watched repo
  (adjust the `working-directory` if your Terraform lives somewhere other
  than `./infra`).
- Add "Infra Cost Guardian" as a **required status check** in branch
  protection rules, so a `hold` verdict actually blocks merge instead of
  just posting a comment.

The workflow template is intentionally kept under `examples/`, not
`.github/workflows/`, so this guardian repo does not accidentally run the
watched-repo workflow when you push it. See `docs/workflow.md` for the full
guardian repo vs. watched repo explanation.

### 5. (Optional) GitHub API token for check runs / PR comments

Set `GUARDIAN_GITHUB_TOKEN` as a Lambda environment variable, sourced from
Secrets Manager, not hardcoded in Terraform state. Without it, the
handler logs what it *would* have posted, so the pipeline is still fully
testable without a token.

---

## The security story: the apply role's permission boundary

`terraform/oidc.tf` defines the exact trust policy the whole project is
about getting right:

```hcl
condition {
  test     = "StringEquals"           # not StringLike, so no wildcard by default
  variable = "token.actions.githubusercontent.com:sub"
  values   = ["repo:${var.github_org}/${var.github_repo}:ref:${var.allowed_ref}"]
}
```

`terraform/iam.tf` then scopes the attached policy to only the resource
types this stack itself provisions (Lambda, DynamoDB, SNS/SQS, and IAM
management *scoped to `terraform-guardian-*`-prefixed roles/policies only*)
and it does not attach a broad managed policy. If you extend this stack to
manage other infrastructure, extend `terraform_apply_scoped` deliberately,
resource type by resource type, rather than reaching for `AdministratorAccess`.

The guardian's own IAM definitions live in a repo the guardian itself
could watch. If someone tried to widen `oidc.tf`'s `StringEquals` to
`StringLike` with a wildcard, the guardian, watching its own repo, would
hold that PR for the same reason it holds the demo's Act 2 PR.

---

## Demo script (5 minutes, two acts)

**Act 1: the boring plan sails through (~60s).** Open a PR bumping Lambda
memory or adding a DynamoDB GSI. Show the PR, the "Infra Cost Guardian"
check run going green, the auto-apply happening, and the DynamoDB log
entry. This establishes the agent isn't a rubber-stamp bot; it looked and
decided.

**Act 2: the OIDC trap.** Open a PR that changes
`token.actions.githubusercontent.com:sub` from
`repo:you/repo:ref:refs/heads/main` to `repo:you/repo:*` (exactly
`tests/fixtures/plan_oidc_trap.json`). Show the check run failing/holding,
the Slack/SNS message with the semantic diff and concrete "this would
newly allow" examples, and, critically, show that a plain `git diff` of
the same change looks like a boring one-line edit to a human skimming it.
That contrast is the whole pitch for building an agent instead of a
keyword-matching CI rule.

---

## The feedback loop (human_override)

`agent/dynamo_store.py` includes `record_human_override`, called from a
separate approval webhook (not built out in this six-week scope) when a
human either approves a held plan ("actually fine, apply it") or flags a
bad auto-apply after the fact. Every decision record has a nullable
`human_override` field for exactly this purpose. It's the training
signal a v2 version of this project would use to tighten or relax
thresholds over time, even without online learning in the current scope.

---

## Known limitations / what's explicitly out of scope for this submission

- `terraform apply` itself is not invoked directly by the Lambda; on an
  `auto_apply` verdict, the handler's `_trigger_apply` is a clearly marked
  integration point for dispatching a follow-up GitHub Actions job that
  runs `terraform apply` under the scoped OIDC role. This keeps the actual
  apply credentials scoped to GitHub Actions' OIDC federation rather than
  living inside the Lambda's own role.
- `cost_estimate.py`'s Infracost path requires the Infracost CLI and an
  API key in the Lambda's environment; without it, the module falls back
  to a small heuristic price table (documented in-file) so the cost check
  never silently no-ops, but the heuristic is coarse by design and should
  not be treated as billing-accurate.
- The "new resource type" check currently does a DynamoDB `Query` with a
  reasonable `Limit` rather than a dedicated GSI; fine for a hackathon
  demo's plan volume, worth revisiting at scale.
- `terraform validate`/`terraform plan` could not be run against these
  `.tf` files in the sandbox used to author this repo (no Terraform CLI
  in that environment's network allowlist). Run both locally before your
  first `apply`.
>>>>>>> 6d9fc48 (feat: add OIDC trust policy diffing and Terraform plan parsing)
