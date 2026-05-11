# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

# Minimal working example. Apply from this directory:
#
#   terraform init
#   terraform apply
#
# By default this brings up an HTTP-only install on the ALB DNS name —
# useful for evaluation. For HTTPS, set `domain_name` and `route53_zone_id`
# below and re-apply.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
}

# In production, prefer declaring the provider here so callers control
# region / profile / assume_role explicitly. For this example we let the
# module's own provider block take effect.

module "observal" {
  source = "../.."

  region      = var.region
  environment = var.environment
  name_prefix = var.name_prefix

  # Uncomment for HTTPS on a real domain:
  # domain_name     = "observal.example.com"
  # route53_zone_id = "Z0123456789ABCDEFGHIJ"

  # Uncomment to use ClickHouse Cloud instead of the bundled EC2:
  # clickhouse_mode           = "cloud"
  # clickhouse_cloud_url      = "https://abc123.us-east-1.aws.clickhouse.cloud:8443"
  # clickhouse_cloud_password = var.clickhouse_cloud_password
}
