# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (e.g. prod, staging). Drives prod-only toggles (RDS Multi-AZ, ElastiCache replication, deletion protection)."
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
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDRs for public subnets (one per AZ). Must match az_count."
  type        = list(string)
  default     = ["10.42.0.0/24", "10.42.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDRs for private subnets (one per AZ). Must match az_count."
  type        = list(string)
  default     = ["10.42.10.0/24", "10.42.11.0/24"]
}

variable "az_count" {
  description = "Number of availability zones to span. ALB and RDS subnet groups need >= 2."
  type        = number
  default     = 2
}

variable "internal_dns_zone" {
  description = "Private Route 53 zone for VPC-internal DNS (e.g. clickhouse.observal.internal)."
  type        = string
  default     = "observal.internal"
}

# ── DNS / TLS ──────────────────────────────────────────────────────────────

variable "domain_name" {
  description = "Public hostname for the install (e.g. observal.example.com). Leave empty to expose only the ALB DNS name over HTTP."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route 53 hosted zone ID for domain_name. Required if domain_name is set."
  type        = string
  default     = ""
}

# ── ECS Fargate (api / web / worker / init) ────────────────────────────────

variable "image_repo_api" {
  description = "Container image repository for api + worker + init (they share an image)."
  type        = string
  default     = "ghcr.io/blazeup-ai/observal-api"
}

variable "image_repo_web" {
  description = "Container image repository for the Next.js web frontend."
  type        = string
  default     = "ghcr.io/blazeup-ai/observal-web"
}

variable "image_tag" {
  description = "Tag of the Observal images to deploy. Bump and re-apply to roll out a new release."
  type        = string
  default     = "latest"
}

variable "api_cpu" {
  description = "Fargate CPU units for the api task (1024 = 1 vCPU)."
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Fargate memory (MB) for the api task."
  type        = number
  default     = 1024
}

variable "api_desired_count" {
  description = "Baseline number of api tasks. Autoscaling overrides between min/max."
  type        = number
  default     = 2
}

variable "api_autoscale_min" {
  description = "Minimum number of api tasks under autoscaling."
  type        = number
  default     = 2
}

variable "api_autoscale_max" {
  description = "Maximum number of api tasks under autoscaling."
  type        = number
  default     = 10
}

variable "web_cpu" {
  description = "Fargate CPU units for the web task."
  type        = number
  default     = 256
}

variable "web_memory" {
  description = "Fargate memory (MB) for the web task."
  type        = number
  default     = 512
}

variable "web_desired_count" {
  description = "Baseline number of web tasks."
  type        = number
  default     = 2
}

variable "web_autoscale_min" {
  description = "Minimum number of web tasks under autoscaling."
  type        = number
  default     = 2
}

variable "web_autoscale_max" {
  description = "Maximum number of web tasks under autoscaling."
  type        = number
  default     = 6
}

variable "worker_cpu" {
  description = "Fargate CPU units for the worker task."
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Fargate memory (MB) for the worker task."
  type        = number
  default     = 1024
}

variable "worker_desired_count" {
  description = "Baseline number of worker tasks."
  type        = number
  default     = 1
}

variable "worker_autoscale_min" {
  description = "Minimum number of worker tasks under autoscaling."
  type        = number
  default     = 1
}

variable "worker_autoscale_max" {
  description = "Maximum number of worker tasks under autoscaling."
  type        = number
  default     = 5
}

variable "service_autoscale_cpu_target" {
  description = "Target CPU utilization (%) for ECS service autoscaling."
  type        = number
  default     = 65
}

variable "run_init_on_apply" {
  description = "Run the migrations/seed task as a one-shot Fargate task whenever image_tag changes."
  type        = bool
  default     = true
}

# ── Data tier (ClickHouse + Grafana + Prometheus on EC2) ───────────────────

variable "clickhouse_mode" {
  description = "Where ClickHouse lives. 'self_hosted' = EC2 + EBS managed by this module. 'cloud' = ClickHouse Cloud, supply clickhouse_cloud_url + clickhouse_cloud_password."
  type        = string
  default     = "self_hosted"
  validation {
    condition     = contains(["self_hosted", "cloud"], var.clickhouse_mode)
    error_message = "clickhouse_mode must be 'self_hosted' or 'cloud'."
  }
}

variable "clickhouse_cloud_url" {
  description = "ClickHouse Cloud DSN (e.g. https://abc123.us-east-1.aws.clickhouse.cloud:8443). Required when clickhouse_mode = 'cloud'."
  type        = string
  default     = ""
  sensitive   = true
}

variable "clickhouse_cloud_password" {
  description = "ClickHouse Cloud password. Required when clickhouse_mode = 'cloud'."
  type        = string
  default     = ""
  sensitive   = true
}

variable "data_instance_type" {
  description = "EC2 instance type for the ClickHouse + Grafana + Prometheus host. 8 GB RAM is the floor for light use."
  type        = string
  default     = "t3.large"
}

variable "data_volume_size_gb" {
  description = "Size of the EBS volume mounted at /data on the data tier host."
  type        = number
  default     = 100
}

# ── Managed data services ──────────────────────────────────────────────────

variable "db_instance_class" {
  description = "RDS instance class for Postgres."
  type        = string
  default     = "db.t4g.small"
}

variable "db_allocated_storage_gb" {
  description = "Allocated storage for RDS (GB). Auto-scales up to db_max_allocated_storage_gb."
  type        = number
  default     = 50
}

variable "db_max_allocated_storage_gb" {
  description = "Storage autoscaling ceiling (GB)."
  type        = number
  default     = 500
}

variable "redis_node_type" {
  description = "ElastiCache node type for Redis."
  type        = string
  default     = "cache.t4g.micro"
}

# ── Access controls ────────────────────────────────────────────────────────

variable "alb_ingress_cidrs" {
  description = "CIDR blocks allowed to reach the ALB. Default is open; restrict for private installs."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# ── Application config ─────────────────────────────────────────────────────

variable "log_retention_days" {
  description = "CloudWatch log retention for application + infrastructure log groups."
  type        = number
  default     = 30
}

# ── Backups ────────────────────────────────────────────────────────────────

variable "backup_bucket_force_destroy" {
  description = "Allow Terraform to destroy the backups bucket even if it contains objects. Set true only for non-prod."
  type        = bool
  default     = false
}

variable "backup_lifecycle_ia_days" {
  description = "Days after which backup objects transition to STANDARD_IA."
  type        = number
  default     = 30
}

variable "backup_lifecycle_glacier_days" {
  description = "Days after which backup objects transition to GLACIER_IR."
  type        = number
  default     = 90
}

variable "backup_lifecycle_expire_days" {
  description = "Days after which backup objects expire. Set to 0 to disable expiration."
  type        = number
  default     = 365
}

variable "enable_public_ops_paths" {
  description = "Expose /docs, /redoc, /openapi.json publicly via the ALB. Set true only for internal or dev deployments. Default false blocks these paths with a 403."
  type        = bool
  default     = false
}

# ── License / Edition ──────────────────────────────────────────────────────

variable "observal_license_key" {
  description = "Observal Enterprise license key. If set, enterprise features are enabled at runtime. Leave empty for community edition."
  type        = string
  default     = ""
  sensitive   = true
}

# ── Demo account seeding (optional, first-deploy only) ────────────────────────

variable "demo_super_admin_email" {
  description = "Email for the demo super-admin account. Leave empty to skip all demo seeding."
  type        = string
  default     = ""
}

variable "demo_super_admin_password" {
  description = "Password for the demo super-admin account."
  type        = string
  default     = ""
  sensitive   = true
}

variable "demo_admin_email" {
  description = "Email for the demo admin account."
  type        = string
  default     = ""
}

variable "demo_admin_password" {
  description = "Password for the demo admin account."
  type        = string
  default     = ""
  sensitive   = true
}

variable "demo_reviewer_email" {
  description = "Email for the demo reviewer account."
  type        = string
  default     = ""
}

variable "demo_reviewer_password" {
  description = "Password for the demo reviewer account."
  type        = string
  default     = ""
  sensitive   = true
}

variable "demo_user_email" {
  description = "Email for the demo user account."
  type        = string
  default     = ""
}

variable "demo_user_password" {
  description = "Password for the demo user account."
  type        = string
  default     = ""
  sensitive   = true
}

# ── Bring-your-own VPC (optional) ─────────────────────────────────────────────
# Set these to deploy into an existing VPC instead of creating a new one.
# When vpc_id is set, Terraform skips creating VPC, subnets, IGW, NAT, and
# route tables. You must provide at least 2 public and 2 private subnet IDs.

variable "vpc_id" {
  description = "Existing VPC ID. Leave empty to create a new VPC."
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "List of existing private subnet IDs (at least 2, in different AZs). Required when vpc_id is set."
  type        = list(string)
  default     = []
}

variable "public_subnet_ids" {
  description = "List of existing public subnet IDs (at least 2, in different AZs). Required when vpc_id is set."
  type        = list(string)
  default     = []
}

