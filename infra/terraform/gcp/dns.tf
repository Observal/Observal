# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

resource "google_compute_global_address" "lb" {
  count = local.enable_custom_domain ? 1 : 0
  name  = "${local.name}-lb-ip"
}

resource "google_compute_managed_ssl_certificate" "app" {
  count = local.enable_custom_domain ? 1 : 0
  name  = "${local.name}-cert"

  managed {
    domains = [var.domain_name]
  }
}

resource "google_compute_region_network_endpoint_group" "api" {
  count                 = local.enable_custom_domain ? 1 : 0
  name                  = "${local.name}-api-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.api.name
  }
}

resource "google_compute_backend_service" "api" {
  count       = local.enable_custom_domain ? 1 : 0
  name        = "${local.name}-api-backend"
  protocol    = "HTTPS"
  timeout_sec = 300

  backend {
    group = google_compute_region_network_endpoint_group.api[0].id
  }
}

resource "google_compute_url_map" "app" {
  count           = local.enable_custom_domain ? 1 : 0
  name            = "${local.name}-url-map"
  default_service = google_compute_backend_service.api[0].id
}

resource "google_compute_target_https_proxy" "app" {
  count            = local.enable_custom_domain ? 1 : 0
  name             = "${local.name}-https-proxy"
  url_map          = google_compute_url_map.app[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.app[0].id]
}

resource "google_compute_global_forwarding_rule" "https" {
  count      = local.enable_custom_domain ? 1 : 0
  name       = "${local.name}-https-fwd"
  target     = google_compute_target_https_proxy.app[0].id
  port_range = "443"
  ip_address = google_compute_global_address.lb[0].address
}

resource "google_compute_url_map" "http_redirect" {
  count = local.enable_custom_domain ? 1 : 0
  name  = "${local.name}-http-redirect"

  default_url_redirect {
    https_redirect = true
    strip_query    = false
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  count   = local.enable_custom_domain ? 1 : 0
  name    = "${local.name}-http-proxy"
  url_map = google_compute_url_map.http_redirect[0].id
}

resource "google_compute_global_forwarding_rule" "http" {
  count      = local.enable_custom_domain ? 1 : 0
  name       = "${local.name}-http-fwd"
  target     = google_compute_target_http_proxy.redirect[0].id
  port_range = "80"
  ip_address = google_compute_global_address.lb[0].address
}

resource "google_dns_record_set" "app" {
  count        = local.enable_custom_domain ? 1 : 0
  name         = "${var.domain_name}."
  type         = "A"
  ttl          = 300
  managed_zone = var.dns_managed_zone_name
  rrdatas      = [google_compute_global_address.lb[0].address]
}
