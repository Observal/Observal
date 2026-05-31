# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

resource "google_compute_network" "main" {
  name                    = local.name
  auto_create_subnetworks = false

  depends_on = [google_project_service.compute]
}

resource "google_compute_subnetwork" "main" {
  name          = "${local.name}-main"
  ip_cidr_range = var.vpc_cidr
  region        = var.region
  network       = google_compute_network.main.id

  private_ip_google_access = true
}

resource "google_compute_router" "main" {
  name    = "${local.name}-router"
  network = google_compute_network.main.id
  region  = var.region
}

resource "google_compute_router_nat" "main" {
  name                               = "${local.name}-nat"
  router                             = google_compute_router.main.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_vpc_access_connector" "main" {
  name          = "${var.name_prefix}-vpc"
  region        = var.region
  ip_cidr_range = var.connector_cidr
  network       = google_compute_network.main.name

  min_instances = 2
  max_instances = 10

  depends_on = [google_project_service.vpcaccess]
}

resource "google_compute_firewall" "allow_internal" {
  name    = "${local.name}-allow-internal"
  network = google_compute_network.main.name

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "icmp"
  }

  source_ranges = [var.vpc_cidr, var.connector_cidr]
}

resource "google_compute_firewall" "allow_iap_ssh" {
  name    = "${local.name}-allow-iap-ssh"
  network = google_compute_network.main.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["data-host"]
}

resource "google_compute_firewall" "allow_health_check" {
  name    = "${local.name}-allow-hc"
  network = google_compute_network.main.name

  allow {
    protocol = "tcp"
    ports    = ["8123", "3000", "9090"]
  }

  source_ranges = ["130.211.0.0/22", "35.191.0.0/16"]
  target_tags   = ["data-host"]
}
