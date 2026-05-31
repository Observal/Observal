# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "GCP region to deploy into."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment name (e.g. prod, staging)."
  type        = string
  default     = "prod"
}

variable "name_prefix" {
  description = "Prefix applied to all resource names."
  type        = string
  default     = "observal"
}

# ── Network ────────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "Primary CIDR for the VPC subnet."
  type        = string
  default     = "10.42.0.0/20"
}

variable "connector_cidr" {
  description = "CIDR for the VPC Access Connector (Serverless VPC Access). Must be /28."
  type        = string
  default     = "10.42.16.0/28"
}

# ── DNS / TLS ──────────────────────────────────────────────────────────────

variable "domain_name" {
  description = "Public hostname for the install (e.g. observal.example.com). Leave empty to use Cloud Run default URL."
  type        = string
  default     = ""
}

variable "dns_managed_zone_name" {
  description = "Cloud DNS managed zone name for domain_name. Required if domain_name is set."
  type        = string
  default     = ""
}

# ── Container images ──────────────────────────────────────────────────────

variable "image_repo_api" {
  description = "Container image repository for api + worker + init."
  type        = string
  default     = "ghcr.io/blazeup-ai/observal-api"
}

variable "image_repo_web" {
  description = "Container image repository for the web frontend."
  type        = string
  default     = "ghcr.io/blazeup-ai/observal-web"
}

variable "image_tag" {
  description = "Image tag to deploy."
  type        = string
  default     = "latest"
}

# ── Cloud Run (api) ───────────────────────────────────────────────────────

variable "api_cpu" {
  description = "CPU allocation for API service (e.g. '1' or '2')."
  type        = string
  default     = "1"
}

variable "api_memory" {
  description = "Memory allocation for API service."
  type        = string
  default     = "1Gi"
}

variable "api_min_instances" {
  description = "Minimum instances for API service."
  type        = number
  default     = 1
}

variable "api_max_instances" {
  description = "Maximum instances for API service."
  type        = number
  default     = 10
}

# ── Cloud Run (web) ───────────────────────────────────────────────────────

variable "web_cpu" {
  description = "CPU allocation for web service."
  type        = string
  default     = "1"
}

variable "web_memory" {
  description = "Memory allocation for web service."
  type        = string
  default     = "512Mi"
}

variable "web_min_instances" {
  description = "Minimum instances for web service."
  type        = number
  default     = 1
}

variable "web_max_instances" {
  description = "Maximum instances for web service."
  type        = number
  default     = 6
}

# ── Cloud Run (worker) ────────────────────────────────────────────────────

variable "worker_cpu" {
  description = "CPU allocation for worker service."
  type        = string
  default     = "1"
}

variable "worker_memory" {
  description = "Memory allocation for worker service."
  type        = string
  default     = "1Gi"
}

variable "worker_min_instances" {
  description = "Minimum instances for worker (should be >= 1 for always-on processing)."
  type        = number
  default     = 1
}

variable "worker_max_instances" {
  description = "Maximum instances for worker."
  type        = number
  default     = 5
}

# ── Data tier (ClickHouse on GCE) ─────────────────────────────────────────

variable "clickhouse_mode" {
  description = "'self_hosted' = GCE instance. 'cloud' = ClickHouse Cloud (supply clickhouse_cloud_url)."
  type        = string
  default     = "self_hosted"
  validation {
    condition     = contains(["self_hosted", "cloud"], var.clickhouse_mode)
    error_message = "clickhouse_mode must be 'self_hosted' or 'cloud'."
  }
}

variable "clickhouse_cloud_url" {
  description = "ClickHouse Cloud DSN. Required when clickhouse_mode = 'cloud'."
  type        = string
  default     = ""
  sensitive   = true
}

variable "data_machine_type" {
  description = "Machine type for the ClickHouse + Grafana + Prometheus GCE instance."
  type        = string
  default     = "e2-standard-2"
}

variable "data_disk_size_gb" {
  description = "Persistent disk size (GB) for the data host."
  type        = number
  default     = 100
}

# ── Cloud SQL ─────────────────────────────────────────────────────────────

variable "db_tier" {
  description = "Cloud SQL machine tier."
  type        = string
  default     = "db-g1-small"
}

variable "db_disk_size_gb" {
  description = "Cloud SQL disk size (GB)."
  type        = number
  default     = 50
}

variable "db_ha_enabled" {
  description = "Enable Cloud SQL high availability (regional) for production."
  type        = bool
  default     = false
}

# ── Memorystore Redis ─────────────────────────────────────────────────────

variable "redis_memory_size_gb" {
  description = "Memorystore Redis memory size in GB."
  type        = number
  default     = 1
}

variable "redis_tier" {
  description = "Memorystore tier: BASIC or STANDARD_HA."
  type        = string
  default     = "BASIC"
  validation {
    condition     = contains(["BASIC", "STANDARD_HA"], var.redis_tier)
    error_message = "redis_tier must be 'BASIC' or 'STANDARD_HA'."
  }
}

# ── Application config ────────────────────────────────────────────────────

variable "data_retention_days" {
  description = "ClickHouse data retention in days."
  type        = number
  default     = 90
}

variable "observal_license_key" {
  description = "Observal Enterprise license key. Leave empty for community edition."
  type        = string
  default     = ""
  sensitive   = true
}

variable "edition" {
  description = "Edition to deploy: 'auto', 'community', or 'enterprise'."
  type        = string
  default     = "auto"
  validation {
    condition     = contains(["auto", "community", "enterprise"], var.edition)
    error_message = "edition must be 'auto', 'community', or 'enterprise'."
  }
}

# ── Backups ───────────────────────────────────────────────────────────────

variable "backup_retention_days" {
  description = "Days to retain backups in GCS before deletion. 0 disables."
  type        = number
  default     = 365
}

variable "backup_nearline_days" {
  description = "Days after which backups transition to Nearline storage."
  type        = number
  default     = 30
}
