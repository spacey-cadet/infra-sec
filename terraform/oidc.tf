# GitHub Actions OIDC identity provider, plus the scoped Terraform-apply role.
#
# This is the piece the whole project is about getting right: the apply
# role's trust policy is scoped to a single repo AND a single ref
# (refs/heads/main by default), using StringEquals (not StringLike with a
# wildcard) wherever an exact match is sufficient. Widening this condition
# is exactly the class of change the guardian agent is built to catch when
# it happens to other roles in a watched repo's plans, so this file also
# doubles as the "what good looks like" reference for the demo.

data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]

  tags = {
    Project = var.project_name
  }
}

# Deliberately narrow trust policy: exact repo, exact ref, StringEquals
# (not StringLike) for both sub and aud. This is the "good" version of the
# condition that the demo's Act 2 shows getting silently widened elsewhere.
data "aws_iam_policy_document" "apply_role_trust" {
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
      values   = ["repo:${var.github_org}/${var.github_repo}:ref:${var.allowed_ref}"]
    }
  }
}

resource "aws_iam_role" "terraform_apply" {
  name               = "${var.project_name}-apply-role"
  assume_role_policy = data.aws_iam_policy_document.apply_role_trust.json

  # Explicit permission boundary is documented in README's "security story"
  # section: this role should be scoped down further per-project to exactly
  # the resource types the watched repo's Terraform is allowed to touch.
  # A generic PowerUser-equivalent policy is intentionally NOT attached
  # here; see iam.tf for the least-privilege policy actually attached.
  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_role_policy_attachment" "apply_role_policy" {
  role       = aws_iam_role.terraform_apply.name
  policy_arn = aws_iam_policy.terraform_apply_scoped.arn
}
