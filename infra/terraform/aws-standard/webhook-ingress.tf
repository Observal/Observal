# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: Apache-2.0

# Public GitHub webhook entry point for private installs (opt-in).
#
# When the main ALB is internal (alb_scheme = "internal") or locked to company
# CIDRs, github.com cannot deliver webhooks, so MCP GitHub sync has nothing to
# react to. This adds a second, internet-facing ALB that:
#   - only accepts traffic from GitHub's published webhook IP ranges,
#   - only listens on HTTPS (GitHub verifies the certificate),
#   - forwards only POST /api/v1/webhooks/github/* to the api tasks,
#   - answers 404 for everything else, so the UI, API and login stay private.
# The receiver also verifies each delivery's HMAC signature before doing anything.

locals {
  webhook_ingress_enabled = var.enable_github_webhook_ingress
  webhook_zone_id         = var.webhook_route53_zone_id != "" ? var.webhook_route53_zone_id : var.route53_zone_id
  webhook_public_url      = local.webhook_ingress_enabled ? "https://${var.webhook_domain_name}" : ""

  # GitHub also publishes IPv6 ranges; the ALB is IPv4-only, so keep IPv4.
  webhook_ingress_cidrs = length(var.webhook_ingress_cidrs) > 0 ? var.webhook_ingress_cidrs : (
    local.webhook_ingress_enabled && length(data.http.github_meta) > 0
    ? [for cidr in jsondecode(data.http.github_meta[0].response_body).hooks : cidr if !strcontains(cidr, ":")]
    : []
  )
}

# Read on every plan, so re-applying picks up changes to GitHub's ranges.
data "http" "github_meta" {
  count = local.webhook_ingress_enabled && length(var.webhook_ingress_cidrs) == 0 ? 1 : 0
  url   = "https://api.github.com/meta"

  request_headers = {
    Accept = "application/vnd.github+json"
  }

  lifecycle {
    postcondition {
      condition     = self.status_code == 200
      error_message = "Could not read GitHub's webhook IP ranges from https://api.github.com/meta (HTTP ${self.status_code}). Retry, or set webhook_ingress_cidrs explicitly."
    }
  }
}

resource "terraform_data" "webhook_ingress_validation" {
  count = local.webhook_ingress_enabled ? 1 : 0

  lifecycle {
    precondition {
      condition     = var.webhook_domain_name != ""
      error_message = "webhook_domain_name is required when enable_github_webhook_ingress is true (GitHub needs a hostname with a valid TLS certificate)."
    }
    precondition {
      condition     = local.webhook_zone_id != ""
      error_message = "A public Route 53 zone for webhook_domain_name is required: set webhook_route53_zone_id (or route53_zone_id)."
    }
    precondition {
      condition     = local.should_create_vpc || (var.public_subnet_ids != null && length(coalesce(var.public_subnet_ids, [])) >= 2)
      error_message = "enable_github_webhook_ingress needs at least 2 public subnets: set public_subnet_ids when vpc_id is set, even if alb_scheme is 'internal'."
    }
    precondition {
      condition     = length(local.webhook_ingress_cidrs) > 0
      error_message = "No webhook source ranges: GitHub's meta API returned no IPv4 hook ranges and webhook_ingress_cidrs is empty."
    }
  }
}

# ── Security group ─────────────────────────────────────────────────────────

resource "aws_security_group" "webhook_alb" {
  count       = local.webhook_ingress_enabled ? 1 : 0
  name        = "${local.name}-webhook-alb"
  description = "GitHub webhook deliveries only."
  vpc_id      = local.vpc_id

  # tfsec:ignore:aws-ec2-no-public-ingress-sgr Limited to GitHub's webhook ranges (or var.webhook_ingress_cidrs).
  ingress {
    description = "HTTPS from GitHub webhook ranges"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = local.webhook_ingress_cidrs
  }

  egress {
    description = "API tasks inside the VPC"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [local.vpc_cidr]
  }

  tags = { Name = "${local.name}-webhook-alb-sg" }
}

# ── Load balancer ──────────────────────────────────────────────────────────

# tfsec:ignore:aws-elb-alb-not-public Public by design; reachable only from GitHub's webhook ranges.
resource "aws_lb" "webhook" {
  count              = local.webhook_ingress_enabled ? 1 : 0
  name               = "${local.name}-hooks"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.webhook_alb[0].id]
  subnets            = local.public_subnet_ids

  drop_invalid_header_fields = true
  tags                       = { Name = "${local.name}-hooks" }

  depends_on = [terraform_data.webhook_ingress_validation]
}

# A target group can belong to only one load balancer, so the api service
# registers into this one as well as the main api target group.
resource "aws_lb_target_group" "api_webhook" {
  count       = local.webhook_ingress_enabled ? 1 : 0
  name        = "${local.name}-hooks-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = local.vpc_id
  target_type = "ip"

  deregistration_delay = 30

  health_check {
    path                = "/readyz"
    matcher             = "200-399"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = { Name = "${local.name}-hooks-tg" }
}

# ── TLS ────────────────────────────────────────────────────────────────────

resource "aws_acm_certificate" "webhook" {
  count             = local.webhook_ingress_enabled ? 1 : 0
  domain_name       = var.webhook_domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [terraform_data.webhook_ingress_validation]
}

resource "aws_route53_record" "webhook_cert_validation" {
  for_each = local.webhook_ingress_enabled ? {
    for dvo in aws_acm_certificate.webhook[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  } : {}

  zone_id         = local.webhook_zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "webhook" {
  count                   = local.webhook_ingress_enabled ? 1 : 0
  certificate_arn         = aws_acm_certificate.webhook[0].arn
  validation_record_fqdns = [for r in aws_route53_record.webhook_cert_validation : r.fqdn]
}

# ── Listener: webhook path only ────────────────────────────────────────────

resource "aws_lb_listener" "webhook" {
  count             = local.webhook_ingress_enabled ? 1 : 0
  load_balancer_arn = aws_lb.webhook[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.webhook[0].certificate_arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Not found"
      status_code  = "404"
    }
  }
}

resource "aws_lb_listener_rule" "webhook_github" {
  count        = local.webhook_ingress_enabled ? 1 : 0
  listener_arn = aws_lb_listener.webhook[0].arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_webhook[0].arn
  }

  condition {
    path_pattern {
      values = ["/api/v1/webhooks/github/*"]
    }
  }

  condition {
    http_request_method {
      values = ["POST"]
    }
  }
}

# ── DNS ────────────────────────────────────────────────────────────────────

resource "aws_route53_record" "webhook" {
  count   = local.webhook_ingress_enabled ? 1 : 0
  zone_id = local.webhook_zone_id
  name    = var.webhook_domain_name
  type    = "A"

  alias {
    name                   = aws_lb.webhook[0].dns_name
    zone_id                = aws_lb.webhook[0].zone_id
    evaluate_target_health = true
  }
}
