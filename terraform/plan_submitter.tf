# Role assumed by the reusable Infra Risk client in a DevOps pipeline.

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
  name               = "${var.project_name}-decision-client"
  assume_role_policy = data.aws_iam_policy_document.plan_submitter_trust.json

  tags = {
    Project = var.project_name
  }
}

data "aws_iam_policy_document" "plan_submitter_permissions" {
  statement {
    sid     = "CallDecisionApi"
    effect  = "Allow"
    actions = ["lambda:InvokeFunctionUrl", "lambda:InvokeFunction"]
    resources = [aws_lambda_function.guardian.arn]
  }
}

resource "aws_iam_role_policy" "plan_submitter_permissions" {
  name   = "${var.project_name}-plan-submitter"
  role   = aws_iam_role.plan_submitter.id
  policy = data.aws_iam_policy_document.plan_submitter_permissions.json
}
