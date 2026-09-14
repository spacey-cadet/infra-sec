# Role assumed by the watched repo's GitHub Actions workflow.
#
# This role is intentionally separate from the apply role. A pull request
# workflow only needs to submit plan JSON to the guardian, so it can write to
# the plan bucket and send one SQS message, but it cannot apply infrastructure.

locals {
  plan_submitter_subjects = [
    "repo:${var.github_org}/${var.github_repo}:pull_request",
    "repo:${var.github_org}/${var.github_repo}:ref:${var.allowed_ref}",
  ]
}

data "aws_iam_policy_document" "plan_submitter_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.plan_submitter_subjects
    }
  }
}

resource "aws_iam_role" "plan_submitter" {
  name               = "${var.project_name}-plan-submitter"
  assume_role_policy = data.aws_iam_policy_document.plan_submitter_trust.json

  tags = {
    Project = var.project_name
  }
}

data "aws_iam_policy_document" "plan_submitter_permissions" {
  statement {
    sid     = "UploadPlanJson"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.plan_artifacts.arn}/plans/${var.github_org}/${var.github_repo}/*",
    ]
  }

  statement {
    sid       = "SendPlanPointer"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.plan_queue.arn]
  }
}

resource "aws_iam_role_policy" "plan_submitter_permissions" {
  name   = "${var.project_name}-plan-submitter"
  role   = aws_iam_role.plan_submitter.id
  policy = data.aws_iam_policy_document.plan_submitter_permissions.json
}
