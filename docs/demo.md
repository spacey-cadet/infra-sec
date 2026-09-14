# Five-Minute Demo Script

This demo is designed for a recorded submission. It shows the same
Strands-backed guardian review path that Lambda uses, but runs it locally
against captured Terraform plan JSON fixtures so the video is reliable.

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

The live production path is documented in `docs/workflow.md`. For the
recording, use:

```bash
python3 demo.py tests/fixtures/plan_safe.json
python3 demo.py tests/fixtures/plan_oidc_trap.json || true
```

The second command exits with code `2` because a held plan is a successful
guardian catch, but it is still a blocked infrastructure change.

## Recording Flow

### 0:00-0:30 - Problem

Say:

> Terraform review is repetitive but high stakes. Most plans are boring, but
> one tiny IAM or GitHub OIDC trust-policy change can silently widen who can
> deploy into AWS. Teams either review everything manually, which wastes time,
> or they move fast and miss dangerous changes.

Show `README.md` and the escalation matrix.

### 0:30-1:00 - What It Is

Say:

> Infra Cost Guardian is a Professional Agent. It runs in the background on
> every Terraform pull request, reviews the structured plan, auto-approves
> boring safe changes, and only interrupts humans when there is a real
> decision: cost spike, IAM touch, new resource type, or OIDC trust widening.

Show:

```text
agent/strands_agent.py
```

Point out the Strands tools:

```text
terraform_plan_parse
terraform_cost_estimate
guardian_decision
```

### 1:00-1:45 - Architecture

Open `docs/workflow.md`.

Say:

> There are two repos. This is the guardian repo: it deploys Lambda, SQS, S3,
> DynamoDB, SNS, and the IAM role a watched repo can assume. The watched repo
> copies the workflow template from `examples/terraform-guardian.yml`.

Show the full path:

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

### 1:45-2:40 - Safe Plan

Run:

```bash
python3 demo.py tests/fixtures/plan_safe.json
```

Say:

> This fixture is a normal Lambda configuration update. The agent parses the
> plan, estimates the cost impact, runs the deterministic decision tool, and
> returns `auto_apply`.

Highlight:

```text
Decision: auto_apply
Risk flags: none
Cost impact: +$0.00/mo
```

### 2:40-4:10 - Dangerous OIDC Change

Run:

```bash
python3 demo.py tests/fixtures/plan_oidc_trap.json || true
```

Say:

> This is the change the project is built to catch. The Terraform diff looks
> like a tiny string edit, but it changes the GitHub Actions subject from one
> protected branch to a wildcard.

Highlight:

```text
Decision: hold
Highest priority: yes
OIDC_TRUST_WIDENED
repo:you/repo:ref:refs/heads/main -> repo:you/repo:*
```

Then say:

> That wildcard means other branches or pull request contexts could become
> newly allowed to assume the AWS role. The guardian fails closed and asks a
> human to approve or reject.

### 4:10-4:40 - AWS Implementation

Show these files:

```text
terraform/plan_submitter.tf
terraform/sqs.tf
terraform/s3.tf
terraform/lambda.tf
agent/handler.py
```

Say:

> In production, the watched repo never calls Lambda directly. It assumes a
> narrowly scoped plan submitter role, uploads `plan.json` to S3, and sends an
> SQS pointer. SQS invokes Lambda. Lambda runs the same Strands-backed review
> path shown in the local demo.

### 4:40-5:00 - Close

Say:

> Infra Cost Guardian removes routine Terraform review from the human queue
> while protecting the dangerous edge cases. It saves developer time on boring
> changes and reserves attention for real infrastructure risk.

## Optional Third Clip

To show cost escalation:

```bash
python3 demo.py tests/fixtures/plan_cost.json || true
```

Expected highlights:

```text
Decision: hold
COST_THRESHOLD_EXCEEDED
aws_nat_gateway
```
