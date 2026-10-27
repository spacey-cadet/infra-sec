# Least-privilege policies: the apply role (used by GitHub Actions to run
# `terraform apply`) and the Lambda execution role (used by the guardian
# agent itself). Neither should ever be broadened without the guardian
# itself reviewing the diff; the guardian's own IAM lives in a repo the
# guardian could watch too.

# This starter policy is scoped to the services this reference stack
# provisions (Lambda, DynamoDB, SNS, SQS, S3, IAM-read). Extend it
# per-project to match exactly what the watched repo's Terraform needs to
# manage, and resist the urge to attach a broad managed policy here.
data "aws_iam_policy_document" "terraform_apply_scoped" {
  statement {
    sid    = "LambdaManage"
    effect = "Allow"
    actions = [
      "lambda:GetFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
      "lambda:CreateFunction", "lambda:DeleteFunction", "lambda:TagResource",
    ]
    resources = ["arn:aws:lambda:*:*:function:${var.project_name}-*"]
  }

  statement {
    sid    = "DynamoManage"
    effect = "Allow"
    actions = [
      "dynamodb:CreateTable", "dynamodb:DescribeTable", "dynamodb:UpdateTable", "dynamodb:DeleteTable",
      "dynamodb:TagResource",
    ]
    resources = ["arn:aws:dynamodb:*:*:table/${var.project_name}-*"]
  }

  statement {
    sid    = "SnsSqsManage"
    effect = "Allow"
    actions = [
      "sns:CreateTopic", "sns:GetTopicAttributes", "sns:SetTopicAttributes", "sns:DeleteTopic", "sns:Subscribe",
      "sqs:CreateQueue", "sqs:GetQueueAttributes", "sqs:SetQueueAttributes", "sqs:DeleteQueue",
    ]
    resources = [
      "arn:aws:sns:*:*:${var.project_name}-*",
      "arn:aws:sqs:*:*:${var.project_name}-*",
    ]
  }

  statement {
    sid       = "IamReadOnlyForPlanning"
    effect    = "Allow"
    actions   = ["iam:GetRole", "iam:GetPolicy", "iam:GetOpenIDConnectProvider", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies"]
    resources = ["*"]
  }

  statement {
    sid    = "IamManageGuardianRolesOnly"
    effect = "Allow"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:UpdateRole", "iam:UpdateAssumeRolePolicy",
      "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
      "iam:TagRole", "iam:CreatePolicy", "iam:DeletePolicy", "iam:CreatePolicyVersion", "iam:DeletePolicyVersion",
    ]
    resources = [
      "arn:aws:iam::*:role/${var.project_name}-*",
      "arn:aws:iam::*:policy/${var.project_name}-*",
    ]
  }
}

resource "aws_iam_policy" "terraform_apply_scoped" {
  name   = "${var.project_name}-apply-scoped-policy"
  policy = data.aws_iam_policy_document.terraform_apply_scoped.json
}

# Lambda execution role for the guardian agent itself.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "guardian_lambda_exec" {
  name               = "${var.project_name}-lambda-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "guardian_lambda_permissions" {
  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }

  statement {
    sid    = "SqsConsume"
    effect = "Allow"
    actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.plan_queue.arn]
  }

  statement {
    sid       = "DynamoReadWrite"
    effect    = "Allow"
    actions   = ["dynamodb:PutItem", "dynamodb:Query", "dynamodb:UpdateItem", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.decisions.arn]
  }

  statement {
    sid       = "SnsPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.hold_notifications.arn]
  }

  statement {
    sid       = "S3ReadPlans"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.plan_artifacts.arn}/*"]
  }
}

resource "aws_iam_role_policy" "guardian_lambda_permissions" {
  name   = "${var.project_name}-lambda-permissions"
  role   = aws_iam_role.guardian_lambda_exec.id
  policy = data.aws_iam_policy_document.guardian_lambda_permissions.json
}
