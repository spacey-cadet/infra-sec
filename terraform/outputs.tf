output "apply_role_arn" {
  description = "ARN of the scoped OIDC apply role for the future auto-apply path. The plan-submission workflow should use plan_submitter_role_arn instead."
  value       = aws_iam_role.terraform_apply.arn
}

output "plan_submitter_role_arn" {
  description = "ARN of the scoped OIDC role the watched repo assumes to upload plan JSON and send an SQS message."
  value       = aws_iam_role.plan_submitter.arn
}

output "plan_queue_url" {
  description = "SQS queue URL that the GitHub Actions workflow pushes plan JSON to."
  value       = aws_sqs_queue.plan_queue.url
}

output "plan_artifacts_bucket" {
  description = "S3 bucket for large plan JSON artifacts."
  value       = aws_s3_bucket.plan_artifacts.bucket
}

output "decisions_table_name" {
  description = "DynamoDB table name for the decision log."
  value       = aws_dynamodb_table.decisions.name
}

output "hold_notifications_topic_arn" {
  description = "SNS topic ARN for hold notifications."
  value       = aws_sns_topic.hold_notifications.arn
}

output "ecr_repository_url" {
  description = "Push the guardian Lambda container image here, then set guardian_image_uri and re-apply."
  value       = aws_ecr_repository.guardian.repository_url
}

output "guardian_lambda_name" {
  value = aws_lambda_function.guardian.function_name
}
