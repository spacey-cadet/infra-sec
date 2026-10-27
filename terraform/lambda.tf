resource "aws_cloudwatch_log_group" "guardian" {
  name              = "/aws/lambda/${var.project_name}-agent"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "guardian" {
  function_name = "${var.project_name}-agent"
  role          = aws_iam_role.guardian_lambda_exec.arn
  timeout       = 60
  memory_size   = 512

  package_type = "Image"
  image_uri    = var.guardian_image_uri != "" ? var.guardian_image_uri : "${aws_ecr_repository.guardian.repository_url}:latest"

  environment {
    variables = {
      GUARDIAN_TABLE_NAME     = aws_dynamodb_table.decisions.name
      GUARDIAN_SNS_TOPIC_ARN  = aws_sns_topic.hold_notifications.arn
      GUARDIAN_APPLY_ROLE_ARN = aws_iam_role.terraform_apply.arn
      # GUARDIAN_GITHUB_TOKEN should be injected via a Lambda environment
      # variable sourced from Secrets Manager in a real deployment, not
      # hardcoded in Terraform state. Left unset here by design.
    }
  }

  depends_on = [aws_cloudwatch_log_group.guardian]

  tags = {
    Project = var.project_name
  }
}

resource "aws_ecr_repository" "guardian" {
  name                 = "${var.project_name}-agent"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Project = var.project_name
  }
}
