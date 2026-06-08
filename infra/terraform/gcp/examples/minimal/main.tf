# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

terraform {
  required_version = ">= 1.6.0"
}

module "observal" {
  source = "../../"

  project_id  = var.project_id
  region      = var.region
  environment = var.environment
  name_prefix = var.name_prefix
  image_tag   = var.image_tag

  domain_name           = var.domain_name
  dns_managed_zone_name = var.dns_managed_zone_name

  observal_license_key = var.observal_license_key
}
