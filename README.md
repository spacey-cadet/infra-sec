# Infra Sec

Infra Risk reviews Terraform plans and returns a deterministic `auto_apply` or
`hold` decision through an IAM-authenticated decision API. The consuming
DevOps pipeline runs Terraform and calls the lightweight `infra-risk` Python
client; it does not need a separate guardian service, plan S3 bucket, or SQS
queue.

## Decision rules

The plain Python evaluator is authoritative and fail-closed:

| Signal | Decision |
|---|---|
| OIDC trust policy widened | Hold, highest priority |
| IAM or policy resource touched | Hold |
| New resource type in this repo's history | Hold |
| Cost change is at least $2/month or 40% of baseline | Hold |
| Parse error or unknown action | Hold |
| No escalation rule triggered | Auto-apply |

Fastino's open-weight GLiNER2.5-Decide checkpoint is available as an optional
pipeline-side advisory classifier. Its output is attached to the API response,
but does not change the deterministic action. This keeps the model useful for
review context without giving a text classifier authority over infrastructure
security policy. Fastino documents GLiNER2 as a local, CPU-capable schema
classification/extraction library and lists Decide as its English
classification specialist ([model and usage documentation](https://github.com/fastino-ai/GLiNER2#-available-models)).

## Use in a watched repository

Copy [`examples/infra-risk.yml`](examples/infra-risk.yml) to
`.github/workflows/infra-risk.yml`, set repository variables
`INFRA_RISK_CLIENT_ROLE_ARN` and `INFRA_RISK_API_URL`, then replace the sample
Git URL with this repository's canonical URL. The action assumes the scoped
AWS role through GitHub OIDC, creates a Terraform plan, and submits it to the
decision API.

To use GLiNER locally in the CI runner, install the optional model extra and
set its checkpoint:

```sh
pip install 'infra-risk[gliner] @ git+https://github.com/YOUR_ORG/infra-risk.git'
export INFRA_RISK_GLINER_MODEL=fastino/GLiNER2.5-Decide
infra-risk --plan plan.json
```

The default package is smaller: `pip install 'infra-risk[aws] ...'` installs
only the AWS signing client. The GLiNER extra downloads PyTorch dependencies
and the model weights on the runner.

## Decision API

`POST` a JSON object containing `repo`, `head_sha`, and `plan_json` to the
Lambda Function URL. Requests are signed with AWS SigV4 and the endpoint
requires AWS IAM authorization.

The Python CLI exits `0` for `auto_apply`, `2` for `hold`, and nonzero on
request/credential errors. CI should treat all nonzero exits as blocked.

## Repository map

- `agent/plan_parser.py`, `agent/oidc_diff.py`, `agent/cost_estimate.py`,
  `agent/decision_engine.py`: deterministic plan analysis.
- `agent/handler.py`: synchronous Function URL API and Lambda entry point.
- `infra_risk/`: small installable pipeline client (`infra-risk` command).
- `terraform/`: Lambda, IAM OIDC access, decision history and notifications.
- `docs/workflow.md`: API and pipeline integration details.
- `tests/`: parser, OIDC diff, decision matrix, and optional agent wrapper coverage.

## Deploy

Terraform requires AWS credentials and Terraform 1.5+. Build and push the
container image to the ECR URL from Terraform output, then set
`infra_risk_image_uri` and apply the stack. The Function URL and scoped GitHub
OIDC client role are exposed as `decision_api_url` and
`plan_submitter_role_arn` outputs. Review the IAM trust inputs (`github_org`,
`github_repo`, `allowed_ref`) before deployment.
