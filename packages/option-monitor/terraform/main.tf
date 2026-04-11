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
  region = var.aws_region
}

# --- DynamoDB ---

resource "aws_dynamodb_table" "alerts" {
  name         = var.dynamodb_table_name
  billing_mode = "PAY_PER_REQUEST" # on-demand, free tier eligible

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
    Service = "option-monitor"
  }
}

# --- SSM Parameter Store ---

resource "aws_ssm_parameter" "credentials" {
  name        = var.ssm_parameter_name
  description = "Option monitor credentials (Webull, Tradier, Discord)"
  type        = "SecureString"
  value       = "{}" # placeholder — populate via AWS CLI after first apply

  tags = {
    Service = "option-monitor"
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
  name               = "option-monitor-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = {
    Service = "option-monitor"
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
    resources = ["arn:aws:logs:${var.aws_region}:*:*"]
  }

  # DynamoDB (monitor: Get/Put, interaction: Update/Scan)
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
  name   = "option-monitor-permissions"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_permissions.json
}

# --- Lambda ---

resource "aws_lambda_function" "monitor" {
  function_name = "option-monitor"
  role          = aws_iam_role.lambda.arn
  handler       = "option_monitor.handler.handler"
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
    Service = "option-monitor"
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${aws_lambda_function.monitor.function_name}"
  retention_in_days = 14

  tags = {
    Service = "option-monitor"
  }
}

# --- EventBridge ---

resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "option-monitor-schedule"
  description         = "Trigger option monitor every 5 min during market hours"
  schedule_expression = var.schedule_expression

  tags = {
    Service = "option-monitor"
  }
}

resource "aws_cloudwatch_event_target" "lambda" {
  rule = aws_cloudwatch_event_rule.schedule.name
  arn  = aws_lambda_function.monitor.arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.monitor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}

# --- Discord Interaction Handler ---

resource "aws_lambda_function" "interaction" {
  function_name = "option-monitor-interaction"
  role          = aws_iam_role.lambda.arn # shares IAM role with monitor
  handler       = "option_monitor.interaction.handler"
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
    Service = "option-monitor"
  }
}

resource "aws_cloudwatch_log_group" "interaction" {
  name              = "/aws/lambda/${aws_lambda_function.interaction.function_name}"
  retention_in_days = 14

  tags = {
    Service = "option-monitor"
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

resource "aws_lambda_permission" "function_url_invoke" {
  statement_id  = "AllowPublicInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.interaction.function_name
  principal     = "*"
}
