# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

output "vpc_id" {
  description = "ID of the created VPC."
  value       = aws_vpc.main.id
}

output "vpc_cidr" {
  description = "CIDR block of the created VPC."
  value       = aws_vpc.main.cidr_block
}

output "public_subnet_ids" {
  description = "IDs of the public subnets."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets."
  value       = aws_subnet.private[*].id
}

output "nat_gateway_ips" {
  description = "Elastic IPs of the NAT gateway."
  value       = [aws_eip.nat.public_ip]
}

output "internet_gateway_id" {
  description = "ID of the internet gateway."
  value       = aws_internet_gateway.main.id
}

output "internal_zone_id" {
  description = "ID of the private Route 53 zone."
  value       = aws_route53_zone.internal.zone_id
}

output "internal_zone_name" {
  description = "Name of the private Route 53 zone."
  value       = aws_route53_zone.internal.name
}

output "flow_logs_log_group_name" {
  description = "Name of the CloudWatch log group for VPC flow logs."
  value       = var.enable_flow_logs ? aws_cloudwatch_log_group.flow_logs[0].name : ""
}
