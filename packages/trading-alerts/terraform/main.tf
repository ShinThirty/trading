terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = "personal"
}

# --- DynamoDB ---

resource "aws_dynamodb_table" "alerts" {
  name         = var.dynamodb_table_name
  billing_mode = "PROVISIONED" # 25 RCU/25 WCU stays inside the always-free tier

  read_capacity  = 25
  write_capacity = 25

  hash_key = "dedup_key"

  attribute {
    name = "dedup_key"
    type = "S"
  }

  ttl {
    attribute_name = "ttl_expire"
    enabled        = true
  }

  tags = {
    Service = "trading-alerts"
  }
}

# --- SSM Parameter Store ---

resource "aws_ssm_parameter" "credentials" {
  name        = var.ssm_parameter_name
  description = "trading-alerts credentials (Discord bot)"
  type        = "SecureString"
  value       = "{}" # placeholder — populate via `make credentials` after first apply

  tags = {
    Service = "trading-alerts"
  }

  lifecycle {
    ignore_changes = [value] # don't overwrite after manual population
  }
}

# --- IAM ---

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "trading-alerts-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = {
    Service = "trading-alerts"
  }
}

data "aws_iam_policy_document" "lambda_permissions" {
  # CloudWatch Logs
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "${aws_cloudwatch_log_group.dispatcher.arn}:*",
      "${aws_cloudwatch_log_group.interaction.arn}:*",
    ]
  }

  # DynamoDB (dispatcher: Get/Put, interaction: Update/Scan)
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.alerts.arn]
  }

  # SSM Parameter Store
  statement {
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.credentials.arn]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "trading-alerts-permissions"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

# --- Lambda — dispatcher (cron-driven watchers) ---

resource "aws_lambda_function" "dispatcher" {
  function_name = "trading-alerts-dispatcher"
  role          = aws_iam_role.lambda.arn
  handler       = "trading_alerts.handler.handler"
  runtime       = "python3.13"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_mb

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  environment {
    variables = {
      SSM_PARAMETER  = var.ssm_parameter_name
      DYNAMODB_TABLE = var.dynamodb_table_name
    }
  }

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_log_group" "dispatcher" {
  name              = "/aws/lambda/${aws_lambda_function.dispatcher.function_name}"
  retention_in_days = 14

  tags = {
    Service = "trading-alerts"
  }
}

# --- EventBridge — per-watcher schedules ---
#
# Each rule fires the dispatcher with a static {"trigger": "<name>"} input,
# which the handler routes to the matching watcher.

# NAAIM publishes Wed afternoon ET; fire Thu morning to ensure the print is live.
resource "aws_cloudwatch_event_rule" "naaim" {
  name                = "trading-alerts-naaim"
  description         = "NAAIM Exposure Index crowding watcher (weekly, Thu)"
  schedule_expression = var.naaim_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "naaim" {
  rule  = aws_cloudwatch_event_rule.naaim.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "naaim" })
}

resource "aws_lambda_permission" "naaim" {
  statement_id  = "AllowEventBridgeNaaim"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.naaim.arn
}

# SqueezeMetrics CSV refreshes ~30 min after market close; fire ~6 PM ET.
resource "aws_cloudwatch_event_rule" "gex" {
  name                = "trading-alerts-gex"
  description         = "GEX (dealer gamma) regime watcher (daily, Mon-Fri after close)"
  schedule_expression = var.gex_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "gex" {
  rule  = aws_cloudwatch_event_rule.gex.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "gex" })
}

resource "aws_lambda_permission" "gex" {
  statement_id  = "AllowEventBridgeGex"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.gex.arn
}

# WPSR publishes Wednesday 10:30 ET; fire ~90 min later for slack.
resource "aws_cloudwatch_event_rule" "wpsr" {
  name                = "trading-alerts-wpsr"
  description         = "EIA Weekly Petroleum Status Report watcher (gas YoY/WoW + SPR)"
  schedule_expression = var.wpsr_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "wpsr" {
  rule  = aws_cloudwatch_event_rule.wpsr.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "wpsr" })
}

resource "aws_lambda_permission" "wpsr" {
  statement_id  = "AllowEventBridgeWpsr"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.wpsr.arn
}

# DIX shares the same SqueezeMetrics CSV as GEX (post-close refresh). A
# separate rule keeps each watcher independently mutable / debuggable.
resource "aws_cloudwatch_event_rule" "dix" {
  name                = "trading-alerts-dix"
  description         = "DIX (dark-pool dollar-weighted short ratio) single-day move watcher"
  schedule_expression = var.dix_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "dix" {
  rule  = aws_cloudwatch_event_rule.dix.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "dix" })
}

resource "aws_lambda_permission" "dix" {
  statement_id  = "AllowEventBridgeDix"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.dix.arn
}

# TSMC publishes monthly revenue ~14:00 Taipei (06:00 UTC) around the 10th of
# each month. Run daily 08:00 UTC during days 5-15 to catch the print whenever
# it lands; dedup keeps the alert to one fire per reported month.
resource "aws_cloudwatch_event_rule" "tsmc_revenue" {
  name                = "trading-alerts-tsmc-revenue"
  description         = "TSMC monthly consolidated revenue watcher (semi cycle leading indicator)"
  schedule_expression = var.tsmc_revenue_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "tsmc_revenue" {
  rule  = aws_cloudwatch_event_rule.tsmc_revenue.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "tsmc_revenue" })
}

resource "aws_lambda_permission" "tsmc_revenue" {
  statement_id  = "AllowEventBridgeTsmcRevenue"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.tsmc_revenue.arn
}

# --- Lambda — Discord interaction handler (mute buttons + slash commands) ---

resource "aws_lambda_function" "interaction" {
  function_name = "trading-alerts-interaction"
  role          = aws_iam_role.lambda.arn # shares IAM role with dispatcher
  handler       = "trading_alerts.interaction.handler"
  runtime       = "python3.13"
  timeout       = 10
  memory_size   = 128

  filename         = var.lambda_zip_path # same deployment package
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  environment {
    variables = {
      DYNAMODB_TABLE     = var.dynamodb_table_name
      DISCORD_PUBLIC_KEY = var.discord_public_key
    }
  }

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_log_group" "interaction" {
  name              = "/aws/lambda/${aws_lambda_function.interaction.function_name}"
  retention_in_days = 14

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_lambda_function_url" "interaction" {
  function_name      = aws_lambda_function.interaction.function_name
  authorization_type = "NONE" # Discord verifies via Ed25519 signature
}

resource "aws_lambda_permission" "function_url_public" {
  statement_id           = "AllowPublicFunctionURL"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.interaction.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}
