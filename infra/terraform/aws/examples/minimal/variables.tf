# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (drives prod-only HA toggles)."
  type        = string
  default     = "prod"
}

variable "name_prefix" {
  description = "Prefix applied to all resource names."
  type        = string
  default     = "observal"
}
