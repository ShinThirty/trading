output "lambda_function_name" {
  value = aws_lambda_function.monitor.function_name
}

output "lambda_function_arn" {
  value = aws_lambda_function.monitor.arn
}

output "dynamodb_table_name" {
  value = aws_dynamodb_table.alerts.name
}

output "eventbridge_rule_arn" {
  value = aws_cloudwatch_event_rule.schedule.arn
}

output "ssm_parameter_arn" {
  value = aws_ssm_parameter.credentials.arn
}

output "interaction_function_url" {
  description = "Set this as the Interactions Endpoint URL in Discord Developer Portal"
  value       = aws_lambda_function_url.interaction.function_url
}
