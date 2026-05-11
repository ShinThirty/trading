variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-west-2"
}

variable "lambda_zip_path" {
  description = "Path to the Lambda deployment package ZIP"
  type        = string
  default     = "../dist/lambda.zip"
}

variable "ssm_parameter_name" {
  description = "SSM Parameter Store name for credentials (SecureString)"
  type        = string
  default     = "/trading-alerts/credentials"
}

variable "dynamodb_table_name" {
  description = "DynamoDB table name for alert state"
  type        = string
  default     = "trading-alerts"
}

variable "naaim_schedule" {
  description = "EventBridge cron for NAAIM watcher (default: Thu 14:00 UTC = 10 AM ET in DST, after Wed PM print)"
  type        = string
  default     = "cron(0 14 ? * THU *)"
}

variable "gex_schedule" {
  description = "EventBridge cron for GEX watcher (default: Mon-Fri 22:00 UTC = 6 PM ET in DST, after SqueezeMetrics CSV refresh)"
  type        = string
  default     = "cron(0 22 ? * MON-FRI *)"
}

variable "tsmc_revenue_schedule" {
  description = "EventBridge cron for TSMC monthly revenue watcher (default: daily 08:00 UTC, days 5-15 — TSMC publishes ~10th, ~14:00 Taipei = 06:00 UTC)"
  type        = string
  default     = "cron(0 8 5-15 * ? *)"
}

variable "lambda_memory_mb" {
  description = "Lambda memory allocation in MB"
  type        = number
  default     = 256
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 60
}

variable "discord_public_key" {
  description = "Discord application public key (hex) for interaction signature verification"
  type        = string
}
