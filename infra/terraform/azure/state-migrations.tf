# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

# Preserve the existing data-host resources while adopting analytics-neutral
# Terraform addresses for the DuckDB deployment.
moved {
  from = azurerm_network_interface.clickhouse
  to   = azurerm_network_interface.analytics
}

moved {
  from = azurerm_linux_virtual_machine.clickhouse
  to   = azurerm_linux_virtual_machine.analytics
}

moved {
  from = tls_private_key.clickhouse
  to   = tls_private_key.analytics
}

moved {
  from = azurerm_key_vault_secret.clickhouse_url
  to   = azurerm_key_vault_secret.analytics_url
}
