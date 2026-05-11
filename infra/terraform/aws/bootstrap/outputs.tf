# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

output "state_bucket" {
  description = "Name of the S3 bucket holding Terraform state. Plug into the main module's backend block as `bucket`."
  value       = aws_s3_bucket.state.bucket
}

output "lock_table" {
  description = "Name of the DynamoDB table for state locking. Plug into the main module's backend block as `dynamodb_table`."
  value       = aws_dynamodb_table.locks.name
}

output "region" {
  description = "Region the state bucket and lock table live in. Plug into the main module's backend block as `region`."
  value       = var.region
}

output "backend_config" {
  description = "Drop-in `backend \"s3\" {}` block for the main module's versions.tf. Copy-paste."
  value       = <<-EOT
    backend "s3" {
      bucket         = "${aws_s3_bucket.state.bucket}"
      key            = "observal/${var.name_prefix}/terraform.tfstate"
      region         = "${var.region}"
      dynamodb_table = "${aws_dynamodb_table.locks.name}"
      encrypt        = true
    }
  EOT
}
