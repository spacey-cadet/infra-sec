resource "aws_sqs_queue" "plan_queue_dlq" {
  name                      = "${var.project_name}-plan-queue-dlq"
  message_retention_seconds = 1209600 # 14 days

  tags = {
    Project = var.project_name
  }
}

resource "aws_sqs_queue" "plan_queue" {
  name                       = "${var.project_name}-plan-queue"
  visibility_timeout_seconds = 90 # >= Lambda timeout
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.plan_queue_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Project = var.project_name
  }
}

resource "aws_lambda_event_source_mapping" "sqs_to_lambda" {
  event_source_arn = aws_sqs_queue.plan_queue.arn
  function_name    = aws_lambda_function.guardian.arn
  batch_size       = 1 # one plan decision per invocation; keeps fail-closed semantics simple
}
