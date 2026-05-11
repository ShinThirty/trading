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

variable "state_bucket_name" {
  description = "S3 bucket holding shared state objects (e.g. pipeline.json published from local trading-mcp)"
  type        = string
  default     = "trading-alerts-state"
}

variable "pipeline_state_key" {
  description = "S3 key for the published pipeline snapshot consumed by ticker-aware watchers"
  type        = string
  default     = "pipeline.json"
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

variable "dix_schedule" {
  description = "EventBridge cron for DIX watcher (default: Mon-Fri 22:00 UTC, same window as gex — same CSV refresh)"
  type        = string
  default     = "cron(0 22 ? * MON-FRI *)"
}

variable "fomc_schedule" {
  description = "EventBridge cron for FOMC watcher (default: Wed 19:30 UTC = 3:30 PM ET in DST, ~90 min after the typical 2:00 PM ET FOMC release; non-FOMC Wednesdays no-op)"
  type        = string
  default     = "cron(30 19 ? * WED *)"
}

variable "gdp_schedule" {
  description = "EventBridge cron for GDP watcher (default: Thu 14:00 UTC = 10 AM ET in DST, ~90 min after the typical Thursday 8:30 ET BEA release; non-GDP Thursdays no-op)"
  type        = string
  default     = "cron(0 14 ? * THU *)"
}

variable "pce_schedule" {
  description = "EventBridge cron for PCE watcher (default: daily 14:30 UTC, days 26-31 — covers the typical 8:30 ET end-month publish; non-PCE days no-op via dedup)"
  type        = string
  default     = "cron(30 14 26-31 * ? *)"
}

variable "cpi_schedule" {
  description = "EventBridge cron for CPI watcher (default: daily 14:30 UTC, days 10-15 — covers the typical 8:30 ET mid-month publish; non-CPI days no-op via dedup)"
  type        = string
  default     = "cron(30 14 10-15 * ? *)"
}

variable "nfp_schedule" {
  description = "EventBridge cron for NFP watcher (default: Fri 14:30 UTC = 10:30 AM ET in DST, ~2h after first-Friday 8:30 ET release; non-NFP Fridays no-op)"
  type        = string
  default     = "cron(30 14 ? * FRI *)"
}

variable "factset_ei_schedule" {
  description = "EventBridge cron for FactSet Earnings Insight watcher (default: Fri 23:00 UTC = 7 PM ET in DST, after typical Friday afternoon publish)"
  type        = string
  default     = "cron(0 23 ? * FRI *)"
}

variable "qra_schedule" {
  description = "EventBridge cron for QRA watcher (default: Wed 14:00 UTC = 10 AM ET in DST, ~90 min after the 8:30 ET release; non-QRA Wednesdays no-op via dedup)"
  type        = string
  default     = "cron(0 14 ? * WED *)"
}

variable "beige_book_schedule" {
  description = "EventBridge cron for Beige Book watcher (default: Wed 19:00 UTC = 3 PM ET in DST, ~1h after the 2 PM ET release)"
  type        = string
  default     = "cron(0 19 ? * WED *)"
}

variable "wpsr_schedule" {
  description = "EventBridge cron for WPSR watcher (default: Wed 16:00 UTC = 12 PM ET in DST, ~90 min after WPSR publishes at 10:30 ET)"
  type        = string
  default     = "cron(0 16 ? * WED *)"
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
