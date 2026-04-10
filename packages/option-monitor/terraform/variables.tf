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
  default     = "/option-monitor/credentials"
}

variable "dynamodb_table_name" {
  description = "DynamoDB table name for alert state"
  type        = string
  default     = "option-monitor-alerts"
}

variable "schedule_expression" {
  description = "EventBridge cron schedule (Mon-Fri, 13:30-20:00 UTC = market hours)"
  type        = string
  default     = "cron(0/5 13-20 ? * MON-FRI *)"
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
