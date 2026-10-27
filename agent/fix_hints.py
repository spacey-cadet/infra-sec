"""fix_hints

Deterministic, per-finding remediation guidance. The InfraSec report embeds
these so the explanation is reproducible; the Duo remediator agent turns them
into an actual Terraform commit, but never decides *whether* to block.
"""

FIX_HINTS = {
    "NETWORK_OPEN_TO_WORLD": "Replace 0.0.0.0/0 / ::/0 with the specific CIDR, VPN range or source security group that needs access. Keep 80/443 world-open only for a public load balancer.",
    "S3_PUBLIC_ACCESS_LOOSENED": "Set all four aws_s3_bucket_public_access_block flags to true, remove public ACLs, and scope bucket policies to named principals or add a Condition.",
    "DB_PUBLICLY_ACCESSIBLE": "Set publicly_accessible = false and reach the database through a private subnet, VPN or bastion.",
    "ENCRYPTION_DISABLED": "Set encryption (storage_encrypted / encrypted) to true, with a KMS key if required.",
    "OIDC_TRUST_WIDENED": "Pin the trust policy 'sub' claim to the exact repo and branch (repo:ORG/REPO:ref:refs/heads/main), use StringEquals, and keep aud = sts.amazonaws.com.",
    "OIDC_TRUST_CHANGED": "Confirm the changed trust condition is still pinned to one repo and ref.",
    "IAM_RESOURCE_TOUCHED": "IAM changes always need a human reviewer. Confirm least privilege (no wildcard actions or resources).",
    "NEW_RESOURCE_TYPE": "First use of this resource type in this repo: have a human confirm it is intended, then add it to .infrasec/known_types.json.",
    "COST_THRESHOLD_EXCEEDED": "Reduce size/count, or have a human approve the cost increase.",
    "UNKNOWN_ACTION": "The plan contains an action InfraSec does not recognise. Re-run with a supported Terraform version.",
    "PARSE_ERROR": "Re-generate the plan with `terraform show -json tfplan.binary > plan.json`.",
}

# Findings an automated agent may fix by itself because the safe fix is a pure
# tightening. Everything else is escalated to a human.
AUTO_FIXABLE = {
    "NETWORK_OPEN_TO_WORLD",
    "S3_PUBLIC_ACCESS_LOOSENED",
    "DB_PUBLICLY_ACCESSIBLE",
    "ENCRYPTION_DISABLED",
    "OIDC_TRUST_WIDENED",
}
