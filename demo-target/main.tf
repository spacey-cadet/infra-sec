# The infrastructure InfraSec guards in the demo. Edit this file (for example, open
# the security group to 0.0.0.0/0) and push: the pipeline plans it, InfraSec holds it,
# and the Duo agent commits the fix.
#
# The provider is configured to plan offline (no AWS account needed). Plans are
# create-only, which is enough because InfraSec inspects the planned "after" state.
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region                      = "us-east-1"
  access_key                  = "offline"
  secret_key                  = "offline"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

resource "aws_s3_bucket" "data" {
  bucket = "infrasec-demo-data"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_security_group" "app" {
  name = "app"

  ingress {
    description = "SSH from the internal network only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
