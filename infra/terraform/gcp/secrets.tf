# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "random_password" "clickhouse" {
  length  = 32
  special = false
}

locals {
  secrets = {
    DATABASE_URL         = local.database_url
    REDIS_URL            = local.redis_url
    SECRET_KEY           = random_password.secret_key.result
    CLICKHOUSE_URL       = local.clickhouse_url
    OBSERVAL_LICENSE_KEY = var.observal_license_key
  }
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
