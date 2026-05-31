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

  # BYO-VPC: when vpc_id is provided, use existing resources; otherwise create new ones.
  create_vpc = var.vpc_id == ""
  vpc_id     = local.create_vpc ? aws_vpc.main[0].id : var.vpc_id
  vpc_cidr   = local.create_vpc ? aws_vpc.main[0].cidr_block : data.aws_vpc.existing[0].cidr_block

  private_subnet_ids = local.create_vpc ? aws_subnet.private[*].id : var.private_subnet_ids
  public_subnet_ids  = local.create_vpc ? aws_subnet.public[*].id : var.public_subnet_ids

  enable_tls = var.domain_name != "" && var.route53_zone_id != ""
  app_url    = local.enable_tls ? "https://${var.domain_name}" : "http://${aws_lb.app.dns_name}"

  clickhouse_self_hosted = var.clickhouse_mode == "self_hosted"

  # Internal DNS name for ClickHouse
  clickhouse_host_internal = local.clickhouse_self_hosted ? "clickhouse.${var.internal_dns_zone}" : ""

  ssm_prefix = "/${local.name}"

  is_enterprise = var.observal_license_key != ""
}

# Lookup existing VPC when using BYO-VPC
data "aws_vpc" "existing" {
  count = local.create_vpc ? 0 : 1
  id    = var.vpc_id
}
