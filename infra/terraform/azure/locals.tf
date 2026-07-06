# SPDX-FileCopyrightText: 2026 Tanvi Reddy
# SPDX-License-Identifier: Apache-2.0

locals {
  name     = "${var.name_prefix}-${var.environment}"
  is_prod  = var.environment == "prod"
  location = var.location

  clickhouse_self_hosted = var.clickhouse_mode == "self_hosted"

  observability_prometheus_enabled = contains(["prometheus", "grafana"], var.observability_stack)
  observability_grafana_enabled    = var.observability_stack == "grafana"

  # VM is needed if ClickHouse, Redis, or bundled Prometheus is self-hosted.
  needs_vm = local.clickhouse_self_hosted || var.redis_mode == "self_hosted" || local.observability_prometheus_enabled

  api_image = "${azurerm_container_registry.main.login_server}/${var.name_prefix}-api:${var.image_tag}"
  web_image = "${azurerm_container_registry.main.login_server}/${var.name_prefix}-web:${var.image_tag}"

  # Connection strings built from managed resources
  database_url      = "postgresql+asyncpg://${azurerm_postgresql_flexible_server.main.administrator_login}:${random_password.db.result}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/observal?ssl=require"
  redis_self_hosted = var.redis_mode == "self_hosted"
  redis_url         = local.redis_self_hosted ? "redis://${azurerm_network_interface.clickhouse[0].private_ip_address}:6379" : "rediss://:${azurerm_redis_enterprise_database.main[0].primary_access_key}@${azurerm_redis_enterprise_cluster.main[0].hostname}:10000"
  clickhouse_url    = local.clickhouse_self_hosted ? "clickhouse://default:${random_password.clickhouse.result}@${azurerm_network_interface.clickhouse[0].private_ip_address}:8123/observal" : var.clickhouse_cloud_url

  tags = {
    Project     = "observal"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "terraform_data" "observability_validation" {
  lifecycle {
    precondition {
      condition     = var.observability_stack == "none" || local.clickhouse_self_hosted
      error_message = "Bundled observability requires clickhouse_mode = self_hosted. Use your cloud provider observability stack when ClickHouse Cloud is enabled."
    }
  }
}
