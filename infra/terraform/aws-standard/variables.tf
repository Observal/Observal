# SPDX-FileCopyrightText: 2026 BlazeUp AI
# SPDX-License-Identifier: AGPL-3.0-only

variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
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

# ── Sizing ────────────────────────────────────────────────────────────────────

variable "sizing" {
  description = "Resource sizing preset: small (~$120/mo) or medium (~$155/mo). Set 'custom' for manual control."
  type        = string
  default     = "medium"

  validation {
    condition     = contains(["small", "medium", "custom"], var.sizing)
    error_message = "sizing must be 'small', 'medium', or 'custom'."
  }
}

# ── Container images ──────────────────────────────────────────────────────────

variable "image_repo_api" {
  description = "Container image repository for api + worker + init."
  type        = string
  default     = "ghcr.io/observal/observal-api"
}

variable "image_repo_web" {
  description = "Container image repository for the web frontend."
  type        = string
  default     = "ghcr.io/observal/observal-web"
}

variable "image_tag" {
  description = "Tag of the Observal images to deploy."
  type        = string
  default     = "latest"
}

# ── ECS EC2 cluster ───────────────────────────────────────────────────────────

variable "ecs_instance_type" {
  description = "EC2 instance type for the ECS cluster (runs API, web, worker containers)."
  type        = string
  default     = "t3.large"
}

variable "api_cpu" {
  description = "CPU units for the API task (only when sizing = custom)."
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Memory (MB) for the API task (only when sizing = custom)."
  type        = number
  default     = 1024
}

variable "api_desired_count" {
  description = "Number of API tasks (only when sizing = custom)."
  type        = number
  default     = 1
}

variable "web_cpu" {
  description = "CPU units for the web task (only when sizing = custom)."
  type        = number
  default     = 256
}

variable "web_memory" {
  description = "Memory (MB) for the web task (only when sizing = custom)."
  type        = number
  default     = 512
}

variable "web_desired_count" {
  description = "Number of web tasks (only when sizing = custom)."
  type        = number
  default     = 1
}

variable "worker_cpu" {
  description = "CPU units for the worker task (only when sizing = custom)."
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Memory (MB) for the worker task (only when sizing = custom)."
  type        = number
  default     = 1024
}

variable "worker_desired_count" {
  description = "Number of worker tasks (only when sizing = custom)."
  type        = number
  default     = 1
}

# ── Data tier EC2 ─────────────────────────────────────────────────────────────

variable "data_instance_type" {
  description = "EC2 instance type for the data host (Postgres + Redis + ClickHouse)."
  type        = string
  default     = "t3.medium"
}

variable "data_volume_size_gb" {
  description = "EBS volume size for the data host."
  type        = number
  default     = 100
}

# ── Network ───────────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones."
  type        = number
  default     = 2
}

variable "internal_dns_zone" {
  description = "Private Route 53 zone for internal DNS."
  type        = string
  default     = "observal.internal"
}

# ── BYO-VPC ───────────────────────────────────────────────────────────────────

variable "vpc_id" {
  description = "Existing VPC ID. Leave null to create a new VPC."
  type        = string
  default     = null

  validation {
    condition     = var.vpc_id == null || can(regex("^vpc-", var.vpc_id))
    error_message = "VPC ID must start with 'vpc-' if provided."
  }
}

variable "private_subnet_ids" {
  description = "Private subnet IDs (required when vpc_id is set)."
  type        = list(string)
  default     = null
}

variable "public_subnet_ids" {
  description = "Public subnet IDs (required when vpc_id is set)."
  type        = list(string)
  default     = null
}

# ── DNS / TLS ─────────────────────────────────────────────────────────────────

variable "domain_name" {
  description = "Public hostname for the install. Leave empty for ALB DNS over HTTP."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone ID. Required if domain_name is set."
  type        = string
  default     = ""
}

variable "enable_tls" {
  description = "Enable TLS via ACM."
  type        = bool
  default     = true
}

# ── Access controls ───────────────────────────────────────────────────────────

variable "alb_ingress_cidrs" {
  description = "CIDR blocks allowed to reach the ALB."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "alb_scheme" {
  description = "ALB scheme: 'internet-facing' or 'internal'."
  type        = string
  default     = "internet-facing"

  validation {
    condition     = contains(["internet-facing", "internal"], var.alb_scheme)
    error_message = "alb_scheme must be 'internet-facing' or 'internal'."
  }
}

# ── Application ───────────────────────────────────────────────────────────────

variable "observability_stack" {
  description = "Bundled observability stack to deploy: none, prometheus, or grafana. grafana includes prometheus."
  type        = string
  default     = "none"

  validation {
    condition     = contains(["none", "prometheus", "grafana"], var.observability_stack)
    error_message = "observability_stack must be one of: none, prometheus, grafana."
  }
}

variable "observal_license_key" {
  description = "Observal Enterprise license key. Leave empty for community."
  type        = string
  default     = ""
  sensitive   = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 30
}

variable "run_init_on_apply" {
  description = "Run migrations task when image_tag changes."
  type        = bool
  default     = true
}
