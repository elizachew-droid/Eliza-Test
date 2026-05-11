output "slack_request_url" {
  description = "Paste this into Slack App > Interactivity & Shortcuts > Request URL"
  value       = "${aws_apigatewayv2_api.this.api_endpoint}/slack/interactions"
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.slack_handler.function_name
}

output "lambda_log_group" {
  description = "CloudWatch log group for Lambda"
  value       = aws_cloudwatch_log_group.lambda_logs.name
}

output "api_gateway_id" {
  description = "API Gateway ID"
  value       = aws_apigatewayv2_api.this.id
}
