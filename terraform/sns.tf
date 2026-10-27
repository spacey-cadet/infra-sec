resource "aws_sns_topic" "hold_notifications" {
  name = "${var.project_name}-hold-notifications"

  tags = {
    Project = var.project_name
  }
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.notification_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.hold_notifications.arn
  protocol  = "email"
  endpoint  = var.notification_email
}
