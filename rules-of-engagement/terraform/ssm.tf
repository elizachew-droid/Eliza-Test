# SSM parameters store all secrets — values must be set manually via AWS Console
# or CLI: aws ssm put-parameter --name "/rules-of-engagement/slack/signing_secret" \
#           --value "YOUR_VALUE" --type SecureString
#
# Terraform creates the parameter shells; actual secret values are set out-of-band
# to avoid them appearing in tfstate.

locals {
  ssm = {
    slack_signing_secret = "${var.ssm_prefix}/slack/signing_secret"
    sf_instance_url      = "${var.ssm_prefix}/salesforce/instance_url"
    sf_client_id         = "${var.ssm_prefix}/salesforce/client_id"
    sf_client_secret     = "${var.ssm_prefix}/salesforce/client_secret"
    sf_username          = "${var.ssm_prefix}/salesforce/username"
    sf_password          = "${var.ssm_prefix}/salesforce/password"
    sf_security_token    = "${var.ssm_prefix}/salesforce/security_token"
  }
}

resource "aws_ssm_parameter" "slack_signing_secret" {
  name        = local.ssm.slack_signing_secret
  description = "Slack app signing secret for request verification"
  type        = "SecureString"
  value       = "PLACEHOLDER_SET_MANUALLY"
  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "sf_instance_url" {
  name        = local.ssm.sf_instance_url
  description = "Salesforce instance URL (e.g. https://checkout.my.salesforce.com)"
  type        = "SecureString"
  value       = "PLACEHOLDER_SET_MANUALLY"
  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "sf_client_id" {
  name        = local.ssm.sf_client_id
  description = "Salesforce Connected App consumer key"
  type        = "SecureString"
  value       = "PLACEHOLDER_SET_MANUALLY"
  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "sf_client_secret" {
  name        = local.ssm.sf_client_secret
  description = "Salesforce Connected App consumer secret"
  type        = "SecureString"
  value       = "PLACEHOLDER_SET_MANUALLY"
  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "sf_username" {
  name        = local.ssm.sf_username
  description = "Salesforce integration user username"
  type        = "SecureString"
  value       = "PLACEHOLDER_SET_MANUALLY"
  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "sf_password" {
  name        = local.ssm.sf_password
  description = "Salesforce integration user password"
  type        = "SecureString"
  value       = "PLACEHOLDER_SET_MANUALLY"
  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "sf_security_token" {
  name        = local.ssm.sf_security_token
  description = "Salesforce integration user security token"
  type        = "SecureString"
  value       = "PLACEHOLDER_SET_MANUALLY"
  lifecycle { ignore_changes = [value] }
}
