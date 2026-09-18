# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.work@gmail.com>
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "random_password" "duckdb" {
  length  = 48
  special = false
}

# Renamed from random_password.clickhouse: keep the deployed token instead of
# rotating it (the data host and every Cloud Run service share this value).
moved {
  from = random_password.clickhouse
  to   = random_password.duckdb
}

resource "random_password" "grafana_admin" {
  length  = 24
  special = false
}

locals {
  secrets = merge(
    {
      DATABASE_URL               = local.database_url
      REDIS_URL                  = local.redis_url
      SECRET_KEY                 = random_password.secret_key.result
      DUCKDB_ANALYTICS_URL       = local.analytics_url
      DUCKDB_ANALYTICS_TOKEN     = random_password.duckdb.result
      GOOGLE_OAUTH_CLIENT_ID     = var.google_oauth_client_id
      GOOGLE_OAUTH_CLIENT_SECRET = var.google_oauth_client_secret
    },
    # Stored in Secret Manager so the bundled Grafana stays retrievable.
    local.observability_grafana_enabled ? { GRAFANA_ADMIN_PASSWORD = random_password.grafana_admin.result } : {}
  )
}

resource "google_secret_manager_secret" "app" {
  for_each  = local.secrets
  secret_id = "${local.name}-${lower(replace(each.key, "_", "-"))}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret_version" "app" {
  for_each    = local.secrets
  secret      = google_secret_manager_secret.app[each.key].id
  secret_data = coalesce(each.value, " ")
}

resource "google_secret_manager_secret_iam_member" "cloud_run_access" {
  for_each  = local.secrets
  secret_id = google_secret_manager_secret.app[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run.email}"
}
