# Infra Risk pipeline integration

Infra Risk is deployed once. A watched repository needs a Terraform plan and a
small Python client invocation; it does not need a separate guardian workflow
that uploads plans to S3 and queues them through SQS.

## Pipeline

1. The CI job runs `terraform plan` and exports `terraform show -json` output.
2. GitHub Actions assumes the scoped `decision-client` role using OIDC.
3. The `infra-risk` package signs a request to the AWS_IAM-protected Lambda
   Function URL with SigV4.
4. Infra Risk parses the plan, estimates cost, applies its deterministic risk
   gates, and returns the decision JSON. It logs the decision and reports it
   to GitHub/SNS using the configured integrations.

The deterministic evaluator remains the only authority for `hold` and
`auto_apply`. Optionally, the pipeline client can run Fastino's open-weight
`fastino/GLiNER2.5-Decide` checkpoint locally and attach its classification as
an advisory. The optional model requires installing `infra-risk[gliner]` and
setting `INFRA_RISK_GLINER_MODEL=fastino/GLiNER2.5-Decide`; it adds model
download and PyTorch overhead to the runner. The default `infra-risk[aws]`
client has no model dependency.

## CI client

Copy `examples/infra-risk.yml` into the consuming repo's workflow directory.
Set repository variables `INFRA_RISK_CLIENT_ROLE_ARN` and
`INFRA_RISK_API_URL`. Replace the example package Git URL with the canonical
Infra Risk repository URL. The assumed role trust is scoped to the configured
GitHub org/repo and pull request/ref subjects.

For another CI system, install the package and run:

```sh
pip install 'infra-risk[aws] @ git+https://github.com/YOUR_ORG/infra-risk.git'
terraform show -json tfplan.binary > plan.json
infra-risk --plan plan.json --api-url "$INFRA_RISK_API_URL"
```

The command exits `0` for `auto_apply`, `2` for `hold`, and nonzero on API or
credential errors. Treat every nonzero exit as a blocked pipeline.

## API payload

`POST` JSON to the Function URL. The minimum request is:

```json
{
  "repo": "org/repo",
  "pr_number": "12",
  "head_sha": "commit-sha",
  "plan_json": "{...terraform show -json output...}",
  "baseline_usd": 5.0
}
```

The response includes `action`, `reasoning`, `risk_flags`, cost impact, and
OIDC trust-policy diff details when applicable. Function URL authentication
uses AWS IAM; clients need the scoped OIDC role and SigV4. Keep the request
within the Lambda Function URL payload limit.
