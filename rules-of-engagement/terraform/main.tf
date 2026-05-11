terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # Uncomment and configure once you have an S3 bucket for remote state
  # backend "s3" {
  #   bucket         = "checkout-terraform-state"
  #   key            = "rules-of-engagement/terraform.tfstate"
  #   region         = "eu-west-1"
  #   dynamodb_table = "terraform-state-lock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "rules-of-engagement"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}
