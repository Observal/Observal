# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.observal.id
}

output "public_ip" {
  description = "Elastic IP address"
  value       = aws_eip.observal.public_ip
}

output "url" {
  description = "Site URL"
  value       = var.domain != "" ? "https://${var.domain}" : "http://${aws_eip.observal.public_ip}"
}

output "ssm_command" {
  description = "Command to connect via SSM"
  value       = "aws ssm start-session --target ${aws_instance.observal.id} --region ${var.region}"
}

output "region" {
  description = "AWS region"
  value       = var.region
}

output "domain" {
  description = "Configured domain (empty if IP-only)"
  value       = var.domain
}

output "observal_ref" {
  description = "Git ref being deployed"
  value       = var.observal_ref
}

output "env_overrides" {
  description = "Environment overrides (for deploy.sh)"
  value       = var.env_overrides
  sensitive   = true
}

output "observal_repo" {
  description = "Git repository URL"
  value       = var.observal_repo
}
