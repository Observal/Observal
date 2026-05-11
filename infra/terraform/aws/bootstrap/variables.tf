# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

variable "region" {
  description = "AWS region the state bucket and lock table live in. Pick the region you'll keep state in long-term — moving an S3 bucket later is painful."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix applied to bucket and table names. Bucket name will be \"<prefix>-tf-state-<account_id>\"; table will be \"<prefix>-tf-locks\". Account ID suffix avoids global-bucket-name collisions."
  type        = string
  default     = "observal"
}
