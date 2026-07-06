# SPDX-FileCopyrightText: 2026 Tanvi Reddy
# SPDX-License-Identifier: Apache-2.0

# Data tier: Azure VM running ClickHouse + Redis + Prometheus via docker-compose.
# The VM is created when clickhouse_mode = "self_hosted" OR redis_mode = "self_hosted".

resource "azurerm_network_interface" "clickhouse" {
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

resource "azurerm_managed_disk" "clickhouse_data" {
  count                = local.needs_vm ? 1 : 0
  name                 = "${local.name}-data-disk"
  location             = azurerm_resource_group.main.location
  resource_group_name  = azurerm_resource_group.main.name
  storage_account_type = "Premium_LRS"
  create_option        = "Empty"
  disk_size_gb         = var.clickhouse_disk_size_gb

  tags = local.tags
}

resource "azurerm_linux_virtual_machine" "clickhouse" {
  count               = local.needs_vm ? 1 : 0
  name                = "${local.name}-data"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  size                = var.clickhouse_vm_size
  admin_username      = "observal"

  network_interface_ids = [azurerm_network_interface.clickhouse[0].id]

  admin_ssh_key {
    username   = "observal"
    public_key = tls_private_key.clickhouse[0].public_key_openssh
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
    clickhouse_password              = random_password.clickhouse.result
    clickhouse_db                    = "observal"
    observability_prometheus_enabled = local.observability_prometheus_enabled
  }))

  identity {
    type = "SystemAssigned"
  }

  tags = local.tags
}

resource "azurerm_virtual_machine_data_disk_attachment" "clickhouse_data" {
  count              = local.needs_vm ? 1 : 0
  managed_disk_id    = azurerm_managed_disk.clickhouse_data[0].id
  virtual_machine_id = azurerm_linux_virtual_machine.clickhouse[0].id
  lun                = 0
  caching            = "ReadOnly"
}

resource "tls_private_key" "clickhouse" {
  count     = local.needs_vm ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 4096
}
