# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

# Artifact Registry remote repo that proxies ghcr.io.
# Cloud Run only supports images from GCR, Artifact Registry, or Docker Hub.
# This transparently caches ghcr.io images so Cloud Run can pull them.

resource "google_project_service" "artifactregistry" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "ghcr_proxy" {
  location      = var.region
  repository_id = "${var.name_prefix}-ghcr"
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"

  remote_repository_config {
    docker_repository {
      custom_repository {
        uri = "https://ghcr.io"
      }
    }
  }

  depends_on = [google_project_service.artifactregistry]
}
