data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/src"
  output_path = "${path.module}/../lambda/dist/handler.zip"
}

resource "aws_lambda_function" "slack_handler" {
  function_name    = var.lambda_function_name
  description      = "Handles Slack DROP/KEEP interactions for Rules of Engagement"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  timeout          = var.lambda_timeout
  memory_size      = var.lambda_memory
  role             = aws_iam_role.lambda_exec.arn

  environment {
    variables = {
      SLACK_SIGNING_SECRET_PARAM = local.ssm.slack_signing_secret
      SF_INSTANCE_URL_PARAM      = local.ssm.sf_instance_url
      SF_CLIENT_ID_PARAM         = local.ssm.sf_client_id
      SF_CLIENT_SECRET_PARAM     = local.ssm.sf_client_secret
      SF_USERNAME_PARAM          = local.ssm.sf_username
      SF_PASSWORD_PARAM          = local.ssm.sf_password
      SF_SECURITY_TOKEN_PARAM    = local.ssm.sf_security_token
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda_logs]
}

resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = var.log_retention_days
}

# IAM role for Lambda
resource "aws_iam_role" "lambda_exec" {
  name = "${var.lambda_function_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_ssm" {
  name = "${var.lambda_function_name}-ssm-policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["ssm:GetParameter"]
      Resource = [
        aws_ssm_parameter.slack_signing_secret.arn,
        aws_ssm_parameter.sf_instance_url.arn,
        aws_ssm_parameter.sf_client_id.arn,
        aws_ssm_parameter.sf_client_secret.arn,
        aws_ssm_parameter.sf_username.arn,
        aws_ssm_parameter.sf_password.arn,
        aws_ssm_parameter.sf_security_token.arn,
      ]
    }]
  })
}
