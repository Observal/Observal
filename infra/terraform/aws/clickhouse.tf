# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

# Data tier: a single EC2 host running ClickHouse + Grafana + Prometheus.
#
# Why one host: ClickHouse needs persistent disk (no managed AWS offering); Grafana
# queries ClickHouse heavily so co-locating avoids cross-AZ latency; Prometheus is
# small and pairs naturally with Grafana. All three are managed via docker-compose
# bootstrapped from user-data.
#
# Why not an ASG: a 1-instance ASG buys nothing for HA (CH state lives on EBS,
# not the instance) and complicates DNS. An aws_instance with a static private IP
# attached via ENI gives stable in-VPC addressing. Outage on instance failure is
# the same either way; the answer for real CH HA is ClickHouse Cloud.
#
# When clickhouse_mode = "cloud", none of the resources in this file are created;
# Grafana + Prometheus are skipped entirely (Grafana with Cloud is left to the
# user — typically AWS Managed Grafana or Grafana Cloud).

data "aws_ami" "al2023" {
  count       = local.clickhouse_self_hosted ? 1 : 0
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# tfsec:ignore:aws-ec2-volume-encryption-customer-key AWS-managed aws/ebs key is encrypted at rest; supply a CMK in the production hardening checklist.
resource "aws_ebs_volume" "data" {
  count             = local.clickhouse_self_hosted ? 1 : 0
  availability_zone = local.azs[0]
  size              = var.data_volume_size_gb
  type              = "gp3"
  encrypted         = true

  tags = { Name = "${local.name}-data" }
}

# Static private IP via primary ENI — gives the host a stable address that
# survives instance replacement.
resource "aws_network_interface" "data_host" {
  count           = local.clickhouse_self_hosted ? 1 : 0
  subnet_id       = local.private_subnet_ids[0]
  security_groups = [aws_security_group.data_host[0].id]

  tags = { Name = "${local.name}-data-host-eni" }
}

locals {
  data_host_user_data = local.clickhouse_self_hosted ? templatefile("${path.module}/user-data.sh.tftpl", {
    region                 = var.region
    ssm_prefix             = local.ssm_prefix
    image_tag              = var.image_tag
    log_group              = aws_cloudwatch_log_group.data_host.name
    backups_bucket         = aws_s3_bucket.backups.bucket
    grafana_admin_user     = "admin"
    clickhouse_db          = "observal"
    grafana_root_url       = local.app_url
    grafana_subpath_prefix = "/grafana"
  }) : ""
}

resource "aws_instance" "data_host" {
  count                = local.clickhouse_self_hosted ? 1 : 0
  ami                  = data.aws_ami.al2023[0].id
  instance_type        = var.data_instance_type
  iam_instance_profile = aws_iam_instance_profile.data_host[0].name

  network_interface {
    device_index         = 0
    network_interface_id = aws_network_interface.data_host[0].id
  }

  user_data                   = local.data_host_user_data
  user_data_replace_on_change = true

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = "${local.name}-data-host" }

  depends_on = [
    aws_nat_gateway.main,
    aws_ssm_parameter.app,
  ]
}

resource "aws_volume_attachment" "data" {
  count       = local.clickhouse_self_hosted ? 1 : 0
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data[0].id
  instance_id = aws_instance.data_host[0].id
}

# ── Internal DNS so ECS tasks can reach ClickHouse + Grafana ───────────────

resource "aws_route53_record" "clickhouse_internal" {
  count   = local.clickhouse_self_hosted ? 1 : 0
  zone_id = aws_route53_zone.internal.zone_id
  name    = "clickhouse.${var.internal_dns_zone}"
  type    = "A"
  ttl     = 60
  records = [aws_network_interface.data_host[0].private_ip]
}

resource "aws_route53_record" "grafana_internal" {
  count   = local.clickhouse_self_hosted ? 1 : 0
  zone_id = aws_route53_zone.internal.zone_id
  name    = "grafana.${var.internal_dns_zone}"
  type    = "A"
  ttl     = 60
  records = [aws_network_interface.data_host[0].private_ip]
}
