# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.70" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
    tls    = { source = "hashicorp/tls", version = "~> 4.0" }
    null   = { source = "hashicorp/null", version = "~> 3.2" }
  }

  # Uncomment and configure once an S3 bucket + DynamoDB lock table exist.
  # backend "s3" {
  #   bucket         = "your-tf-state-bucket"
  #   key            = "observal/prod/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "your-tf-lock-table"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "Observal"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}
