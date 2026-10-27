import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.suggest import suggest, to_markdown

APP = '''
import os
import boto3

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
table = ddb.Table("jobs")
sqs = boto3.client("sqs")

def run():
    s3.get_object(Bucket="b", Key="k")
    s3.upload_file("a", "b", "c")
    s3.list_objects_v2(Bucket="b")
    table.put_item(Item={})
    boto3.client("sns").publish(TopicArn="t", Message="m")
    sqs.get_paginator("list_queues")
    token = os.environ["SLACK_API_TOKEN"]
    level = os.environ.get("LOG_LEVEL")
    region = os.getenv("AWS_REGION")
'''

WORKFLOW_BAD = """
on: push
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::1:role/x
"""

WORKFLOW_OK = "permissions:\n  id-token: write\n" + WORKFLOW_BAD


def make_repo(tmp_path, workflow=WORKFLOW_BAD, requirements="requests\n"):
    (tmp_path / "app.py").write_text(APP)
    (tmp_path / "requirements.txt").write_text(requirements)
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "deploy.yml").write_text(workflow)
    return tmp_path


def codes(s):
    return [f.code for f in s.findings]


def test_iam_actions_derived_from_real_sdk_calls(tmp_path):
    s = suggest(make_repo(tmp_path), repo="acme/ml-pipeline")
    actions = {u.iam for u in s.usages}
    assert {"s3:GetObject", "s3:PutObject", "s3:ListBucket", "dynamodb:PutItem", "sns:Publish",
            "sqs:ListQueues"} <= actions
    assert all(u.line > 0 for u in s.usages)


def test_generated_iam_never_uses_wildcard_resources(tmp_path):
    s = suggest(make_repo(tmp_path), repo="acme/ml-pipeline")
    iam = s.files["iam.tf"]
    assert 'resources = ["*"]' not in iam and '"*"' not in iam
    assert '"${var.s3_bucket_arn}/*"' in iam          # objects scoped to the bucket
    assert "resources = [var.s3_bucket_arn]" in iam   # ListBucket on the bucket itself
    for var in ("s3_bucket_arn", "dynamodb_table_arn", "sns_topic_arn", "sqs_queue_arn"):
        assert f'variable "{var}"' in s.files["variables.tf"]


def test_missing_id_token_permission_is_flagged(tmp_path):
    s = suggest(make_repo(tmp_path), repo="acme/ml-pipeline")
    f = next(f for f in s.findings if f.code == "OIDC_MISSING_ID_TOKEN_PERMISSION")
    assert f.severity == "critical" and "id-token: write" in f.fix


def test_correct_workflow_is_not_flagged(tmp_path):
    s = suggest(make_repo(tmp_path, workflow=WORKFLOW_OK), repo="acme/ml-pipeline")
    assert "OIDC_MISSING_ID_TOKEN_PERMISSION" not in codes(s)


def test_oidc_trust_is_pinned_to_repo_and_branch(tmp_path):
    s = suggest(make_repo(tmp_path), repo="acme/ml-pipeline")
    oidc = s.files["oidc.tf"]
    assert 'repo:acme/ml-pipeline:ref:refs/heads/main' in oidc
    assert "StringEquals" in oidc and "StringLike" not in oidc
    assert "repo:acme/ml-pipeline:*" not in oidc


def test_unknown_repo_uses_placeholder_and_says_so(tmp_path):
    s = suggest(make_repo(tmp_path))  # tmp_path is not a git repo
    assert "REPO_UNKNOWN" in codes(s) and "repo:ORG/REPO:" in s.files["oidc.tf"]


def test_missing_boto3_package_flagged_and_present_is_not(tmp_path):
    assert "PACKAGE_MISSING" in codes(suggest(make_repo(tmp_path), repo="a/b"))
    ok = tmp_path / "ok"
    ok.mkdir()
    assert "PACKAGE_MISSING" not in codes(suggest(make_repo(ok, requirements="boto3>=1.34\n"), repo="a/b"))


def test_secret_env_var_flagged_and_routed_to_secret_arns(tmp_path):
    s = suggest(make_repo(tmp_path), repo="a/b")
    assert any(f.code == "SECRET_IN_ENV" and "SLACK_API_TOKEN" in f.message for f in s.findings)
    env = s.files["app_env.tf"]
    assert "LOG_LEVEL" in env and "SLACK_API_TOKEN" in env
    assert "AWS_REGION" not in env                      # ambient, ignored
    assert env.index("SLACK_API_TOKEN") > env.index("app_secret_arns")   # in the secrets map only


def test_javascript_sdk_commands(tmp_path):
    (tmp_path / "index.mjs").write_text(
        'import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";\n'
        'import { PublishCommand } from "@aws-sdk/client-sns";\n')
    (tmp_path / "package.json").write_text('{"dependencies": {"@aws-sdk/client-s3": "^3.0.0"}}')
    s = suggest(tmp_path, repo="a/b")
    assert {"s3:GetObject", "sns:Publish"} <= {u.iam for u in s.usages}
    missing = [f for f in s.findings if f.code == "PACKAGE_MISSING"]
    assert len(missing) == 1 and "client-sns" in missing[0].message


def test_unverified_service_is_marked_check(tmp_path):
    (tmp_path / "a.py").write_text('import boto3\nc = boto3.client("sagemaker")\nc.create_training_job()\n')
    s = suggest(tmp_path, repo="a/b")
    assert s.usages[0].iam == "sagemaker:CreateTrainingJob" and s.usages[0].confidence == "check"
    assert "IAM_ACTION_UNVERIFIED" in codes(s)


def test_repo_with_no_aws_usage_suggests_nothing(tmp_path):
    (tmp_path / "x.py").write_text("print('hi')\n")
    s = suggest(tmp_path, repo="a/b")
    assert not s.files and "No infrastructure needs" in to_markdown(s)


def test_generated_terraform_parses(tmp_path):
    hcl2 = pytest.importorskip("hcl2")
    s = suggest(make_repo(tmp_path), repo="acme/ml-pipeline")
    import io
    for name, body in s.files.items():
        assert hcl2.load(io.StringIO(body)), name
