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

  # License: if edition is "auto", infer from license key presence
  effective_edition = var.edition == "auto" ? (var.observal_license_key != "" ? "enterprise" : "community") : var.edition
  is_enterprise     = local.effective_edition == "enterprise"

  # Enterprise uses a separate API image (includes compiled insights);
  # the web image is identical for both editions (gating is server-side).
  image_repo_api_effective = local.is_enterprise ? "ghcr.io/blazeup-ai/observal-api-enterprise" : var.image_repo_api
  image_repo_web_effective = var.image_repo_web
}
