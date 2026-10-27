
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
=======
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
