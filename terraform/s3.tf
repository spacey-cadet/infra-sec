resource "aws_s3_bucket" "plan_artifacts" {
  bucket = "${var.project_name}-plan-artifacts-${data.aws_caller_identity.current.account_id}"

  tags = {
    Project = var.project_name
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "plan_artifacts_expiry" {
  bucket = aws_s3_bucket.plan_artifacts.id
  rule {
    id     = "expire-old-plans"
    status = "Enabled"
    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_public_access_block" "plan_artifacts" {
  bucket                  = aws_s3_bucket.plan_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_caller_identity" "current" {}
