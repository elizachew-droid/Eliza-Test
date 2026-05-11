variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-west-1"
}

variable "aws_profile" {
  description = "AWS CLI profile name (from aws configure sso). Override via -var or AWS_PROFILE env var."
  type        = string
  default     = "checkout-prod"
}

variable "environment" {
  description = "Deployment environment (e.g. prod, staging)"
  type        = string
  default     = "prod"
}

variable "lambda_function_name" {
  description = "Name of the Lambda function that handles Slack interactions"
  type        = string
  default     = "rules-of-engagement-slack-handler"
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds (must stay under 3s for synchronous Slack responses)"
  type        = number
  default     = 10
}

variable "lambda_memory" {
  description = "Lambda memory in MB"
  type        = number
  default     = 256
}

variable "api_gateway_name" {
  description = "Name of the HTTP API Gateway"
  type        = string
  default     = "rules-of-engagement-api"
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

# SSM parameter paths — values are managed separately (see ssm.tf)
variable "ssm_prefix" {
  description = "Prefix for all SSM Parameter Store paths"
  type        = string
  default     = "/rules-of-engagement"
}
