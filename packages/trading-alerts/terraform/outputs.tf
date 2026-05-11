output "dispatcher_function_name" {
  value = aws_lambda_function.dispatcher.function_name
}

output "dispatcher_function_arn" {
  value = aws_lambda_function.dispatcher.arn
}

output "dynamodb_table_name" {
  value = aws_dynamodb_table.alerts.name
}

output "state_bucket_name" {
  value = aws_s3_bucket.state.id
}

output "naaim_rule_arn" {
  value = aws_cloudwatch_event_rule.naaim.arn
}

output "gex_rule_arn" {
  value = aws_cloudwatch_event_rule.gex.arn
}

output "ssm_parameter_arn" {
  value = aws_ssm_parameter.credentials.arn
}

output "interaction_function_url" {
  description = "Set this as the Interactions Endpoint URL in Discord Developer Portal"
  value       = aws_lambda_function_url.interaction.function_url
}
