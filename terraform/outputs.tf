output "apply_role_arn" {
  description = "ARN of the scoped OIDC apply role for the future apply integration."
  value       = aws_iam_role.terraform_apply.arn
}

output "plan_submitter_role_arn" {
  description = "ARN of the scoped OIDC role assumed by the Infra Risk client to invoke the decision API."
  value       = aws_iam_role.plan_submitter.arn
}

output "decision_api_url" {
  description = "IAM-authenticated Infra Risk decision endpoint URL."
  value       = aws_lambda_function_url.decision_api.function_url
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
  description = "ECR repository for the Infra Risk decision API container image."
  value       = aws_ecr_repository.guardian.repository_url
}

output "infra_risk_lambda_name" {
  value = aws_lambda_function.guardian.function_name
}
