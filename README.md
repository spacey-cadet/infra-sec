# InfraSec

> **License:** MIT, see [LICENSE](LICENSE). **Stack:** deterministic Python gate, GitLab CI, AWS Lambda decision API, NVIDIA Nemotron on Nebius Token Factory.

**AI does the work. Deterministic code decides. A human approves what reaches production.**

InfraSec reviews Terraform changes before they ship. A plain-Python evaluator reads the Terraform plan and returns `auto_apply` or `hold`. When a change is held, an NVIDIA Nemotron model served on Nebius Token Factory explains it on the merge request in plain language, then proposes a small Terraform fix. The deterministic gate re-checks the fix and it is kept only if the gate now says `auto_apply`. The model never produces the verdict, and production deploys are a manual job.

## What it does

1. **Gate (deterministic).** `scripts/infrasec_decide.py` scores `terraform show -json` output with no AWS account and no network. It also records whether conventional CI (`terraform fmt`/`validate`, tests) passed, and the report says whether CI alone would have shipped the change.
2. **Explain (Nemotron on Token Factory).** If the gate holds a branch, `infrasec:explain` runs `scripts/infrasec_explain.py`. It sends the decision JSON and the Terraform diff to Nemotron and posts a three-part note (what changed, why it was held, rollback plan) on the open merge request.
3. **Fix (Nemotron on Token Factory, verified by the gate).** If every finding is auto-fixable (a pure tightening such as `NETWORK_OPEN_TO_WORLD`) and the attempt budget is not used up, `infrasec:fix` runs `scripts/infrasec_fix.py`. Nemotron returns the corrected `.tf` file; the script applies it, regenerates the plan, and re-runs the gate. Kept and committed (tagged `[infrasec-autofix]`) only if the gate returns `auto_apply`; otherwise it is reverted and the MR note says a human is needed.
4. **Human approval.** `deploy:staging` runs after the gate passes on the default branch. `deploy:production` is a **manual** job and waits for a person to start it.

```mermaid
flowchart LR
    A[Push to branch] --> B[Plan + CI checks]
    B --> C{InfraSec gate<br/>deterministic}
    C -- hold --> D[Nemotron explains<br/>on the MR]
    C -- hold --> E[Nemotron proposes fix]
    E --> H{Gate re-checks<br/>patched plan}
    H -- auto_apply --> I[Commit to MR branch]
    H -- still hold --> J[Revert, ask a human]
    C -- auto_apply, default branch --> F[Deploy staging]
    F --> G[Human starts<br/>deploy:production]
```

The principle: **never let a model invent the risk number.** Decisions are reproducible and auditable because the score never comes from a model.

## How this project uses NVIDIA Nemotron and Nebius Token Factory

Two scripts call Nebius Token Factory through its OpenAI-compatible API (`https://api.tokenfactory.nebius.com/v1`) with a Nemotron model chosen by `NEBIUS_MODEL_ID`. Both use only the Python standard library, so there is no SDK to install.

**Explain: `scripts/infrasec_explain.py`**

- **Advisory only.** The system prompt forbids re-scoring or questioning the verdict, which comes from the evaluator. The script exits `0` in every case: with no key set, no model set, or Token Factory unreachable it prints a message and the pipeline carries on unchanged.
- **Grounded input.** The prompt contains only the decision JSON and the `.tf` diff (both truncated to a fixed size), and asks for exactly three short sections.
- **Reasoning output stripped.** Any `<think>...</think>` block is removed before the note is posted.
- **Output.** The note is printed in the job log and posted on the merge request, headed "Explanation by NVIDIA Nemotron on Nebius Token Factory (advisory only)".

**Fix: `scripts/infrasec_fix.py`**

- **Only pure tightenings.** It runs only when every finding is in the auto-fixable set (open-to-world networking, public S3/DB, disabled encryption, widened OIDC trust). IAM, new resource types, cost and parse errors always go to a human, and the model is not even called.
- **Guardrails before anything is written.** One existing `.tf` file only, at most 10 changed lines, and the set of resources must be identical (no adding, removing or renaming). The model also sees the previous version from the target branch so it can restore the exact old value.
- **The gate has the final say.** The patched file is formatted, planned and re-evaluated by the same deterministic evaluator. Anything other than `auto_apply` reverts the file.
- **Bounded and quiet.** The attempt budget is shared with the rest of the loop, a failure or timeout changes nothing, and the script always exits `0`.
- **Not a rubber stamp.** The gate only checks the signals listed under [Decision rules](#decision-rules). Keeping the diff small and the resources fixed limits what a bad proposal can do, and a person still starts `deploy:production`.

Environment variables:

| Variable | Purpose |
|---|---|
| `NEBIUS_API_KEY` | Token Factory API key (masked CI/CD variable) |
| `NEBIUS_MODEL_ID` | Nemotron model id from the Token Factory catalog |
| `NEBIUS_BASE_URL` | Optional, defaults to `https://api.tokenfactory.nebius.com/v1` |
| `INFRASEC_TOKEN` | Project access token (`api` and `write_repository`, Developer role) used to post MR notes and push the fix |

Pick a model id:

```bash
NEBIUS_API_KEY=... python scripts/infrasec_explain.py --list-models
```

## Try the demo

The demo target is `demo-target/main.tf`, which defines `aws_security_group.app` with SSH open to `10.0.0.0/8`. The provider is configured to plan offline, so **no AWS credentials are needed**.

**Locally, with a saved plan:**

```bash
pip install -r requirements.txt pytest
python scripts/infrasec_decide.py --plan demo/plans/ssh_open.json --ci-status pass
# exit code 2 = held; writes infrasec-decision.json and infrasec-report.md
NEBIUS_API_KEY=... NEBIUS_MODEL_ID=... python scripts/infrasec_explain.py --decision infrasec-decision.json
```

Saved plans: `demo/plans/ssh_open.json` (held), `demo/plans/s3_public.json` (held), `demo/plans/safe.json` (passes).

**On GitLab:**

1. Add CI/CD variables `NEBIUS_API_KEY` (masked), `NEBIUS_MODEL_ID` and `INFRASEC_TOKEN` (project access token, `api` + `write_repository`, Developer role).
2. Create a branch from `main`, change the SSH `cidr_blocks` in `demo-target/main.tf` to `["0.0.0.0/0"]`, push it and open a merge request.
3. `infrasec:decide` fails and holds the change. `infrasec:explain` posts the Nemotron note, and `infrasec:fix` asks Nemotron for the fix. If the gate approves the patched file, it is committed back to the branch, the pipeline re-runs and passes, and `infrasec:automerge` merges the merge request. Production still waits for a person.
4. Without `AWS_ACCESS_KEY_ID`, the deploy jobs print `DEMO MODE` and apply nothing.

## Decision rules

The plain Python evaluator is authoritative and fail-closed:

| Signal                                              | Decision               |
|-----------------------------------------------------|------------------------|
| OIDC trust policy widened                           | Hold, highest priority |
| IAM or policy resource touched                      | Hold                   |
| New resource type in this repo's history            | Hold                   |
| Cost change is at least $2/month or 40% of baseline | Hold                   |
| Parse error or unknown action                       | Hold                   |
| No escalation rule triggered                        | Auto-apply             |

Findings also carry codes such as `NETWORK_OPEN_TO_WORLD`, `S3_PUBLIC_ACCESS_LOOSENED`, `DB_PUBLICLY_ACCESSIBLE`, `ENCRYPTION_DISABLED` and `OIDC_TRUST_WIDENED`.

Fastino's open-weight GLiNER2.5-Decide checkpoint is available as an optional advisory classifier. Its output is attached to the API response but never changes the deterministic action. See the [model documentation](https://github.com/fastino-ai/GLiNER2#-available-models).

## Alternative: GitLab Duo auto-fix

Built for the GitLab AI Hackathon and kept as an alternative to the Nemotron fix. It needs GitLab Duo Agent Platform and two CI/CD variables. Use one fixer or the other: leave `INFRASEC_FLOW_HANDLE` unset when `infrasec:fix` is your fixer, because `infrasec:notify` only mentions the Duo flow when that variable is set.

- `flows/infrasec-autofix.yaml` (paste into Automate > Flows) explains a held change and, only when every finding is auto-fixable and the attempt budget is not used up, commits the previous value back, tagged `[infrasec-autofix]`.
- `scripts/infrasec_automerge.py` merges that fix after the gate re-run passes. It only merges a head commit tagged `[infrasec-autofix]`, and only when the merge request is not a draft and has no conflicts.
- Guardrails: the agent never edits IAM permissions, `scripts/`, `agent/`, `tests/`, `.gitlab-ci.yml` or `.infrasec/`, and attempts are capped.
- Variables: `INFRASEC_TOKEN` and `INFRASEC_FLOW_HANDLE` (the `@handle` GitLab autocompletes for the flow).

Auto-merge into the default branch is automatic for these tagged fixes. Reaching production still requires a person to start `deploy:production`.

## Decision API (AWS)

The same evaluator is deployed as an IAM-authenticated AWS Lambda Function URL. `POST` a JSON object containing `repo`, `head_sha` and `plan_json`; requests are signed with AWS SigV4. The `infra-risk` CLI exits `0` for `auto_apply`, `2` for `hold`, and nonzero on request or credential errors. CI should treat all nonzero exits as blocked. The endpoint is not publicly callable, so the demo above uses the offline gate instead.

To use it from another repository, copy [`examples/infra-risk.yml`](examples/infra-risk.yml) to `.github/workflows/infra-risk.yml` and set repository variables `INFRA_RISK_CLIENT_ROLE_ARN` and `INFRA_RISK_API_URL`. To add the optional GLiNER classifier on the runner:

```bash
pip install 'infra-risk[gliner] @ git+https://github.com/spacey-cadet/infra-sec.git'
export INFRA_RISK_GLINER_MODEL=fastino/GLiNER2.5-Decide
infra-risk --plan plan.json
```

The default package is smaller: `pip install 'infra-risk[aws] ...'` installs only the AWS signing client.

Deploying the API needs AWS credentials and Terraform 1.5+. Build and push the container image to the ECR URL from Terraform output, set `infra_risk_image_uri` and apply `terraform/`. Review the IAM trust inputs (`github_org`, `github_repo`, `allowed_ref`) before deployment.

## Repository map

- `agent/`: deterministic plan analysis (`plan_parser.py`, `oidc_diff.py`, `cost_estimate.py`, `decision_engine.py`) and the Lambda entry point `handler.py`.
- `scripts/infrasec_decide.py`: the offline gate. `scripts/infrasec_explain.py`: the Nemotron explanation. `scripts/infrasec_fix.py`: the Nemotron fix, re-checked by the gate. `scripts/infrasec_notify.py` and `scripts/infrasec_automerge.py`: notification and merging of tagged fixes (the Duo flow is an alternative).
- `infra_risk/`: installable pipeline client (`infra-risk` command).
- `.gitlab-ci.yml`: pipeline wiring. `flows/`: GitLab Duo flows.
- `demo-target/`: the Terraform the demo changes. `demo/plans/`: saved plans.
- `terraform/`: Lambda, IAM OIDC access, decision history and notifications.
- `docs/`: `workflow.md` (API and pipeline details), `decision_engine.md`, `NEBIUS_SUBMISSION.md`.
- `tests/`: parser, OIDC diff, decision matrix, notify, auto-merge, explain and fix coverage. The explain and fix tests use a local fake server, so no key is needed; the fix tests include a bad proposal, an oversized diff and a changed resource set, all of which must leave the file untouched.

```bash
pip install -r requirements.txt pytest
python -m pytest tests -q
```

## Hackathon history

- **GitLab AI Hackathon (submitted, frozen):** the deterministic gate, the Duo explain-and-fix loop, the suggester and the AWS decision API. Autonomy level: Supervised.
- **Nebius x NVIDIA Global AI Hackathon (this repository):** new in this period are the Nemotron explanation and the Nemotron-proposed, gate-verified fix on Nebius Token Factory (`scripts/infrasec_explain.py`, `scripts/infrasec_fix.py`, their tests and the `infrasec:explain` and `infrasec:fix` jobs), a manual `deploy:production` gate, and this README. The evaluator itself is unchanged by design.

## XERJ Corpus Hub
XERJ is  an open-source, AI-native search engine that it gives coding agents the exact passage of code or documentation they need instead of letting them guess from memory. 
[![XERJ Corpus Hub contributor](https://hub.xerj.org/contributors/spacey-cadet/badge.svg)](https://hub.xerj.org/contributors/spacey-cadet)

## License
MIT. See [LICENSE](LICENSE).
