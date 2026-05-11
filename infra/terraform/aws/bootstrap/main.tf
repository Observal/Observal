# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

# One-time bootstrap. Creates the S3 bucket + DynamoDB lock table that the
# main module's `backend "s3"` block points at. Run this once per AWS account
# before the first `terraform init` of the main module.
#
# This module's own state is local — that's intentional. It's small,
# rarely-changed, and bootstrapping a state backend with itself is the
# chicken-and-egg problem we're solving.

data "aws_caller_identity" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  bucket_name = "${var.name_prefix}-tf-state-${local.account_id}"
  table_name  = "${var.name_prefix}-tf-locks"
}

# ── State bucket ───────────────────────────────────────────────────────────
# tfsec:ignore:aws-s3-enable-bucket-logging Access logging would loop into another bucket; out of scope for bootstrap.
# tfsec:ignore:aws-s3-encryption-customer-key AES256 is sufficient for state at the bootstrap tier; supply a CMK if your compliance posture requires it.
resource "aws_s3_bucket" "state" {
  bucket = local.bucket_name

  # Bootstrap is the foundation — make accidental destruction loud.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "state_tls_only" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state_tls_only.json

  depends_on = [aws_s3_bucket_public_access_block.state]
}

# ── Lock table ─────────────────────────────────────────────────────────────
# tfsec:ignore:aws-dynamodb-table-customer-key AWS-managed encryption is the default and sufficient for state locks.
resource "aws_dynamodb_table" "locks" {
  name         = local.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}
