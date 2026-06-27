# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

locals {
  name = "${var.name_prefix}-${var.environment}"

  enable_custom_domain = var.domain_name != "" && var.dns_managed_zone_name != ""
  app_url              = local.enable_custom_domain ? "https://${var.domain_name}" : google_cloud_run_v2_service.api.uri

  clickhouse_self_hosted = var.clickhouse_mode == "self_hosted"

  observability_prometheus_enabled = contains(["prometheus", "grafana"], var.observability_stack)
  observability_grafana_enabled    = var.observability_stack == "grafana"

  effective_edition = var.edition == "auto" ? (var.observal_license_key != "" ? "enterprise" : "community") : var.edition
  is_enterprise     = local.effective_edition == "enterprise"

  ar_prefix = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.ghcr_proxy.repository_id}"

  image_repo_api_effective = local.is_enterprise ? "observal/observal-api-enterprise" : trimprefix(var.image_repo_api, "ghcr.io/")
  image_repo_web_effective = local.is_enterprise ? "observal/observal-web-enterprise" : trimprefix(var.image_repo_web, "ghcr.io/")

  image_api = "${local.ar_prefix}/${local.image_repo_api_effective}:${var.image_tag}"
  image_web = "${local.ar_prefix}/${local.image_repo_web_effective}:${var.image_tag}"

  database_url   = "postgresql+asyncpg://${google_sql_user.app.name}:${random_password.db.result}@${google_sql_database_instance.postgres.private_ip_address}:5432/${google_sql_database.app.name}"
  redis_url      = "redis://${google_redis_instance.main.host}:${google_redis_instance.main.port}"
  clickhouse_url = local.clickhouse_self_hosted ? "clickhouse://default:${random_password.clickhouse.result}@${google_compute_instance.data_host[0].network_interface[0].network_ip}:8123/observal" : var.clickhouse_cloud_url
}

resource "terraform_data" "observability_validation" {
  lifecycle {
    precondition {
      condition     = var.observability_stack == "none" || local.clickhouse_self_hosted
      error_message = "Bundled observability requires clickhouse_mode = self_hosted. Use your cloud provider observability stack when ClickHouse Cloud is enabled."
    }
  }
}
