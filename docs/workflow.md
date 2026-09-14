# Infra Cost Guardian Workflow

This project has two repos in mind:

- **Guardian repo**: this repo. It contains the Lambda agent, Terraform for
  the AWS resources, and the copy/paste workflow template.
- **Watched repo**: the repo that contains Terraform you want protected.
  This is where the GitHub Actions workflow actually runs.

The workflow template belongs in the watched repo, not in this guardian repo:

```text
guardian repo
  agent/
  terraform/
  examples/terraform-guardian.yml
  docs/workflow.md

watched repo
  .github/workflows/terraform-guardian.yml
  infra/
```

## What The Guardian Repo Deploys

The guardian repo creates the AWS side:

- Lambda container running the Strands-backed guardian agent
- SQS queue for plan-review requests
- S3 bucket for full Terraform plan JSON files
- DynamoDB table for decision history
- SNS topic for hold notifications
- GitHub OIDC provider
- Plan submitter IAM role for watched repos
- Apply IAM role for the future auto-apply path

The important role for the watched repo is:

```text
plan_submitter_role_arn
```

That role can only:

```text
s3:PutObject
sqs:SendMessage
```

It cannot apply infrastructure. It only lets the watched repo hand a plan to
the guardian.

## What The Watched Repo Does

The watched repo copies:

```text
examples/terraform-guardian.yml
```

to:

```text
.github/workflows/terraform-guardian.yml
```

Then it adds these GitHub Actions variables:

```text
GUARDIAN_PLAN_SUBMITTER_ROLE_ARN = terraform output plan_submitter_role_arn
GUARDIAN_QUEUE_URL               = terraform output plan_queue_url
GUARDIAN_PLAN_BUCKET             = terraform output plan_artifacts_bucket
```

When a pull request changes Terraform, GitHub Actions:

1. Assumes `GUARDIAN_PLAN_SUBMITTER_ROLE_ARN` through GitHub OIDC.
2. Runs `terraform plan -out=tfplan.binary`.
3. Runs `terraform show -json tfplan.binary > plan.json`.
4. Uploads `plan.json` to the guardian S3 bucket.
5. Sends an SQS message pointing to the uploaded plan JSON.

The SQS message looks like:

```json
{
  "repo": "your-org/your-watched-repo",
  "pr_number": "12",
  "head_sha": "abc123",
  "plan_id": "abc123",
  "plan_json_s3_uri": "s3://terraform-guardian-plan-artifacts-123456789/plans/your-org/your-watched-repo/12/abc123.json"
}
```

## What The Guardian Agent Does

The SQS queue invokes Lambda automatically. Lambda downloads the plan JSON
from S3 and passes it through the Strands agent wrapper in
`agent/strands_agent.py`.

The Strands-exposed tools are:

- `terraform_plan_parse`: extracts normalized resource changes from the
  Terraform JSON plan.
- `terraform_cost_estimate`: estimates the monthly cost delta.
- `guardian_decision`: applies the deterministic escalation matrix.

The final decision is always one of:

```text
auto_apply
hold
```

For a safe change, the agent records an `auto_apply` decision. For risky
changes, such as an IAM/OIDC trust-policy widening or a cost spike, it records
`hold`, sends an SNS notification, and posts GitHub feedback when a token is
configured.

## Why The Workflow Is Not Active In This Repo

This repo is the guardian repo. If the workflow lived at:

```text
.github/workflows/terraform-guardian.yml
```

then GitHub would run it whenever this repo is pushed or receives a PR. That
would be confusing because this repo is not necessarily the watched repo.

Instead, the workflow lives at:

```text
examples/terraform-guardian.yml
```

That makes it a template. Users copy it into whichever repo they want the
guardian to watch.

## Full Path

```text
PR in watched repo
  -> GitHub Actions assumes plan submitter role
  -> Terraform creates plan.json
  -> plan.json uploads to S3
  -> SQS receives pointer to plan.json
  -> Lambda is invoked by SQS
  -> Strands agent tools review the plan
  -> decision is stored in DynamoDB
  -> safe plans auto-apply path, risky plans hold and notify
```
