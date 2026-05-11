# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  name = "${var.name_prefix}-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  enable_tls = var.domain_name != "" && var.route53_zone_id != ""
  app_url    = local.enable_tls ? "https://${var.domain_name}" : "http://${aws_lb.app.dns_name}"

  clickhouse_self_hosted = var.clickhouse_mode == "self_hosted"

  # Internal DNS name for ClickHouse — ECS tasks resolve it via the private Route53 zone.
  clickhouse_host_internal = local.clickhouse_self_hosted ? "clickhouse.${var.internal_dns_zone}" : ""

  ssm_prefix = "/${local.name}"
}
