variable "aws_region" {
  description = "AWS region to deploy the guardian stack into."
  type        = string
  default     = "us-east-1"
}

variable "github_org" {
  description = "GitHub org or user that owns the repo(s) this guardian watches."
  type        = string
}

variable "github_repo" {
  description = "GitHub repo name (without org prefix) this guardian primarily watches, used to scope the apply-role OIDC trust condition."
  type        = string
}

variable "allowed_ref" {
  description = "Git ref allowed to assume the apply role via OIDC, e.g. refs/heads/main. Kept narrow on purpose: this is the exact condition the OIDC-widening demo is about."
  type        = string
  default     = "refs/heads/main"
}

variable "project_name" {
  description = "Name prefix for all resources in this stack."
  type        = string
  default     = "terraform-guardian"
}

variable "guardian_image_uri" {
  description = "ECR image URI for the guardian Lambda container (built from the repo's Dockerfile). Leave blank on first apply and fill in after the first `docker push`."
  type        = string
  default     = ""
}

variable "notification_email" {
  description = "Email address subscribed to the SNS hold-notification topic. Optional; Slack/chat integration can be wired separately."
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the guardian Lambda."
  type        = number
  default     = 30
}
