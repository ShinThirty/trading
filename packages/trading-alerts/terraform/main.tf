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

# --- S3 — shared state ---
#
# Holds the pipeline snapshot (pipeline.json) published from the local
# trading-mcp pipeline_* tools. Lambda watchers read it on cold start to
# filter ticker-aware alerts to the active pipeline universe.

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "state" {
  bucket = "${var.state_bucket_name}-${data.aws_caller_identity.current.account_id}"

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
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

  # S3 — read-only access to the published pipeline snapshot
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.state.arn}/${var.pipeline_state_key}"]
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
      SSM_PARAMETER         = var.ssm_parameter_name
      DYNAMODB_TABLE        = var.dynamodb_table_name
      PIPELINE_STATE_BUCKET = aws_s3_bucket.state.id
      PIPELINE_STATE_KEY    = var.pipeline_state_key
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

# FOMC issues a statement at the end of each scheduled meeting (8x/year),
# typically Wed 2:00 PM ET. Run weekly Wed 19:30 UTC (~3:30 PM ET); non-FOMC
# Wednesdays no-op via meeting-date dedup.
resource "aws_cloudwatch_event_rule" "fomc" {
  name                = "trading-alerts-fomc"
  description         = "FOMC statement new-release watcher"
  schedule_expression = var.fomc_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "fomc" {
  rule  = aws_cloudwatch_event_rule.fomc.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "fomc" })
}

resource "aws_lambda_permission" "fomc" {
  statement_id  = "AllowEventBridgeFomc"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.fomc.arn
}

# GDP publishes 12x/year (4 quarters × 3 estimates) at 8:30 AM ET, typically
# Thursday. Run weekly Thu 14:00 UTC; non-GDP Thursdays no-op via slug dedup.
resource "aws_cloudwatch_event_rule" "gdp" {
  name                = "trading-alerts-gdp"
  description         = "BEA Gross Domestic Product (GDP) new-release watcher"
  schedule_expression = var.gdp_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "gdp" {
  rule  = aws_cloudwatch_event_rule.gdp.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "gdp" })
}

resource "aws_lambda_permission" "gdp" {
  statement_id  = "AllowEventBridgeGdp"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.gdp.arn
}

# PCE publishes near month-end at 8:30 AM ET. Run daily 14:30 UTC during
# days 26-31; non-PCE days no-op via slug dedup.
resource "aws_cloudwatch_event_rule" "pce" {
  name                = "trading-alerts-pce"
  description         = "BEA Personal Income & Outlays (PCE) new-release watcher"
  schedule_expression = var.pce_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "pce" {
  rule  = aws_cloudwatch_event_rule.pce.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "pce" })
}

resource "aws_lambda_permission" "pce" {
  statement_id  = "AllowEventBridgePce"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.pce.arn
}

# CPI publishes mid-month at 8:30 AM ET (typical days 10-15). Run daily
# 14:30 UTC during that window; non-CPI days no-op via dedup.
resource "aws_cloudwatch_event_rule" "cpi" {
  name                = "trading-alerts-cpi"
  description         = "BLS Consumer Price Index new-release watcher"
  schedule_expression = var.cpi_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "cpi" {
  rule  = aws_cloudwatch_event_rule.cpi.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "cpi" })
}

resource "aws_lambda_permission" "cpi" {
  statement_id  = "AllowEventBridgeCpi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.cpi.arn
}

# NFP publishes the first Friday of each month at 8:30 AM ET. Run Fri
# 14:30 UTC (10:30 AM ET); non-NFP Fridays no-op via period dedup.
resource "aws_cloudwatch_event_rule" "nfp" {
  name                = "trading-alerts-nfp"
  description         = "BLS Employment Situation (NFP) new-release watcher"
  schedule_expression = var.nfp_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "nfp" {
  rule  = aws_cloudwatch_event_rule.nfp.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "nfp" })
}

resource "aws_lambda_permission" "nfp" {
  statement_id  = "AllowEventBridgeNfp"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.nfp.arn
}

# FactSet Earnings Insight publishes Friday afternoon ET. Run Fri 23:00 UTC
# = ~7 PM ET. Watcher walks back up to 4 Fridays to find the latest live PDF
# and dedupes on the publish date.
resource "aws_cloudwatch_event_rule" "factset_ei" {
  name                = "trading-alerts-factset-ei"
  description         = "FactSet Earnings Insight weekly PDF release watcher"
  schedule_expression = var.factset_ei_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "factset_ei" {
  rule  = aws_cloudwatch_event_rule.factset_ei.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "factset_ei" })
}

resource "aws_lambda_permission" "factset_ei" {
  statement_id  = "AllowEventBridgeFactsetEi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.factset_ei.arn
}

# QRA Policy Statement is released 4x/year (early Feb / May / Aug / Nov)
# Wednesday 8:30 AM ET. Run weekly Wednesday 14:00 UTC; non-QRA Wednesdays
# no-op via slug dedup.
resource "aws_cloudwatch_event_rule" "qra" {
  name                = "trading-alerts-qra"
  description         = "Treasury Quarterly Refunding Announcement Policy Statement watcher"
  schedule_expression = var.qra_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "qra" {
  rule  = aws_cloudwatch_event_rule.qra.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "qra" })
}

resource "aws_lambda_permission" "qra" {
  statement_id  = "AllowEventBridgeQra"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.qra.arn
}

# Beige Book publishes Wednesday 2 PM ET, 8x/year ~2 weeks before each FOMC.
# Run weekly Wed 19:00 UTC; dedup keeps the alert to one fire per release.
resource "aws_cloudwatch_event_rule" "beige_book" {
  name                = "trading-alerts-beige-book"
  description         = "Federal Reserve Beige Book new-release watcher"
  schedule_expression = var.beige_book_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "beige_book" {
  rule  = aws_cloudwatch_event_rule.beige_book.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "beige_book" })
}

resource "aws_lambda_permission" "beige_book" {
  statement_id  = "AllowEventBridgeBeigeBook"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.beige_book.arn
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

# TSMC files monthly revenue with the exchange ~the 10th, but the TWSE
# open-data feed (t187ap05_L) — our source — only regenerates around the 17th.
# Run daily 08:00 UTC during days 5-20 to catch the feed refresh whenever it
# lands; dedup keeps the alert to one fire per reported month.
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

# Material 8-K (signal-bearing items: 1.01, 1.02, 2.01, 2.05, 2.06, 4.01, 4.02,
# 5.02, 7.01, 8.01) for pipeline tickers. Daily morning before market open;
# LOOKBACK_DAYS=2 + dispatcher dedup handles overlap if a run is missed.
resource "aws_cloudwatch_event_rule" "material_8k" {
  name                = "trading-alerts-material-8k"
  description         = "Material 8-K watcher for pipeline tickers (signal-bearing item codes only)"
  schedule_expression = var.material_8k_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "material_8k" {
  rule  = aws_cloudwatch_event_rule.material_8k.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "material_8k" })
}

resource "aws_lambda_permission" "material_8k" {
  statement_id  = "AllowEventBridgeMaterial8k"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.material_8k.arn
}

# Schedule 13D / 13D/A activist filings for pipeline tickers. Same daily
# morning cadence as material_8k, staggered 15 min so the two ticker-aware
# scans don't double-tap EDGAR's rate limit in the same second.
resource "aws_cloudwatch_event_rule" "activist_filing" {
  name                = "trading-alerts-activist-filing"
  description         = "Schedule 13D activist filing watcher for pipeline tickers"
  schedule_expression = var.activist_filing_schedule

  tags = {
    Service = "trading-alerts"
  }
}

resource "aws_cloudwatch_event_target" "activist_filing" {
  rule  = aws_cloudwatch_event_rule.activist_filing.name
  arn   = aws_lambda_function.dispatcher.arn
  input = jsonencode({ trigger = "activist_filing" })
}

resource "aws_lambda_permission" "activist_filing" {
  statement_id  = "AllowEventBridgeActivistFiling"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.activist_filing.arn
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
