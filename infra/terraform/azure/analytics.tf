# SPDX-FileCopyrightText: 2026 Tanvi Reddy
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

# Data tier: Azure VM running the DuckDB analytics service (+ Redis and
# Prometheus when self-hosted) via docker-compose.
# The VM hosts the DuckDB analytics singleton (plus Redis/Prometheus when
# self-hosted).

resource "azurerm_network_interface" "analytics" {
  count               = local.needs_vm ? 1 : 0
  name                = "${local.name}-data-nic"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.vm.id
    private_ip_address_allocation = "Dynamic"
  }

  tags = local.tags
}

# Renamed from clickhouse_data: keep the existing disk instead of planning a
# destroy/recreate that would wipe the analytics dataset.
moved {
  from = azurerm_managed_disk.clickhouse_data
  to   = azurerm_managed_disk.analytics_data
}

resource "azurerm_managed_disk" "analytics_data" {
  count                = local.needs_vm ? 1 : 0
  name                 = "${local.name}-data-disk"
  location             = azurerm_resource_group.main.location
  resource_group_name  = azurerm_resource_group.main.name
  storage_account_type = "Premium_LRS"
  create_option        = "Empty"
  disk_size_gb         = var.analytics_disk_size_gb

  tags = local.tags
}

resource "azurerm_linux_virtual_machine" "analytics" {
  count               = local.needs_vm ? 1 : 0
  name                = "${local.name}-data"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  size                = var.analytics_vm_size
  admin_username      = "observal"

  network_interface_ids = [azurerm_network_interface.analytics[0].id]

  admin_ssh_key {
    username   = "observal"
    public_key = tls_private_key.analytics[0].public_key_openssh
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {
    image_tag                        = var.image_tag
    duckdb_analytics_token           = random_password.duckdb.result
    duckdb_db                        = "observal"
    observability_prometheus_enabled = local.observability_prometheus_enabled
  }))

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

moved {
  from = azurerm_virtual_machine_data_disk_attachment.clickhouse_data
  to   = azurerm_virtual_machine_data_disk_attachment.analytics_data
}

resource "azurerm_virtual_machine_data_disk_attachment" "analytics_data" {
  count              = local.needs_vm ? 1 : 0
  managed_disk_id    = azurerm_managed_disk.analytics_data[0].id
  virtual_machine_id = azurerm_linux_virtual_machine.analytics[0].id
  lun                = 0
  caching            = "ReadOnly"
}

resource "tls_private_key" "analytics" {
  count     = local.needs_vm ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 4096
}
