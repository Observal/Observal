# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "name_prefix" {
  type    = string
  default = "observal"
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "domain_name" {
  type    = string
  default = ""
}

variable "dns_managed_zone_name" {
  type    = string
  default = ""
}

variable "observal_license_key" {
  type      = string
  default   = ""
  sensitive = true
}
