# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

# All VPC networking resources are conditional on local.create_vpc.
# When vpc_id is provided (BYO-VPC), none of these are created.

resource "aws_vpc" "main" {
  count                = local.create_vpc ? 1 : 0
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  count  = local.create_vpc ? 1 : 0
  vpc_id = aws_vpc.main[0].id
  tags   = { Name = "${local.name}-igw" }
}

# tfsec:ignore:aws-ec2-no-public-ip-subnet Public subnets host the ALB and NAT gateway only; application workloads live in private subnets.
resource "aws_subnet" "public" {
  count                   = local.create_vpc ? var.az_count : 0
  vpc_id                  = aws_vpc.main[0].id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name}-public-${local.azs[count.index]}"
    Tier = "public"
  }
}

resource "aws_subnet" "private" {
  count             = local.create_vpc ? var.az_count : 0
  vpc_id            = aws_vpc.main[0].id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "${local.name}-private-${local.azs[count.index]}"
    Tier = "private"
  }
}

resource "aws_eip" "nat" {
  count  = local.create_vpc ? 1 : 0
  domain = "vpc"
  tags   = { Name = "${local.name}-nat-eip" }
}

resource "aws_nat_gateway" "main" {
  count         = local.create_vpc ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id
  tags          = { Name = "${local.name}-nat" }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  count  = local.create_vpc ? 1 : 0
  vpc_id = aws_vpc.main[0].id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main[0].id
  }
  tags = { Name = "${local.name}-public-rt" }
}

resource "aws_route_table" "private" {
  count  = local.create_vpc ? 1 : 0
  vpc_id = aws_vpc.main[0].id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[0].id
  }
  tags = { Name = "${local.name}-private-rt" }
}

resource "aws_route_table_association" "public" {
  count          = local.create_vpc ? var.az_count : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

resource "aws_route_table_association" "private" {
  count          = local.create_vpc ? var.az_count : 0
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[0].id
}

# ── Flow Logs (only for managed VPC) ──────────────────────────────────────

data "aws_iam_policy_document" "flow_logs_assume" {
  count = local.create_vpc ? 1 : 0
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "flow_logs_publish" {
  count = local.create_vpc ? 1 : 0
  # tfsec:ignore:aws-iam-no-policy-wildcards Resource wildcard is bounded to log streams within the flow-log group only.
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    resources = ["${aws_cloudwatch_log_group.flow_logs.arn}:*"]
  }
}

resource "aws_iam_role" "flow_logs" {
  count              = local.create_vpc ? 1 : 0
  name               = "${local.name}-flow-logs"
  assume_role_policy = data.aws_iam_policy_document.flow_logs_assume[0].json
}

resource "aws_iam_role_policy" "flow_logs" {
  count  = local.create_vpc ? 1 : 0
  role   = aws_iam_role.flow_logs[0].id
  policy = data.aws_iam_policy_document.flow_logs_publish[0].json
}

resource "aws_flow_log" "main" {
  count           = local.create_vpc ? 1 : 0
  vpc_id          = local.vpc_id
  log_destination = aws_cloudwatch_log_group.flow_logs.arn
  iam_role_arn    = aws_iam_role.flow_logs[0].arn
  traffic_type    = "ALL"

  tags = { Name = "${local.name}-flow-logs" }
}

# ── Private DNS zone for VPC-internal resolution (ECS -> ClickHouse/Grafana) ──

resource "aws_route53_zone" "internal" {
  name = var.internal_dns_zone

  vpc {
    vpc_id = local.vpc_id
  }

  tags = { Name = "${local.name}-internal-zone" }
}
