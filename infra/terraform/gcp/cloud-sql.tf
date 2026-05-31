# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "postgres" {
  name                = "${local.name}-pg"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = var.environment == "prod"

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    disk_size         = var.db_disk_size_gb
    disk_autoresize   = true
    availability_type = var.db_ha_enabled ? "REGIONAL" : "ZONAL"

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = var.environment == "prod"
      start_time                     = "03:00"
      transaction_log_retention_days = 7

      backup_retention_settings {
        retained_backups = 14
      }
    }

    maintenance_window {
      day          = 7
      hour         = 4
      update_track = "stable"
    }

    database_flags {
      name  = "max_connections"
      value = "200"
    }
  }

  depends_on = [
    google_project_service.sqladmin,
    google_service_networking_connection.private,
  ]
}

resource "google_sql_database" "app" {
  name     = "observal"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "app" {
  name     = "observal"
  instance = google_sql_database_instance.postgres.name
  password = random_password.db.result
}
