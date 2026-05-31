# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

resource "google_redis_instance" "main" {
  name               = "${local.name}-redis"
  region             = var.region
  memory_size_gb     = var.redis_memory_size_gb
  tier               = var.redis_tier
  redis_version      = "REDIS_7_2"
  authorized_network = google_compute_network.main.id

  redis_configs = {
    maxmemory-policy = "allkeys-lru"
  }

  depends_on = [google_project_service.redis]
}
