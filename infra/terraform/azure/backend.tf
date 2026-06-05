# SPDX-FileCopyrightText: 2026 Tanvi Reddy
# SPDX-License-Identifier: AGPL-3.0-only

# Remote state stored in Azure Blob Storage.
# The storage account is created out-of-band (see README).

terraform {
  backend "azurerm" {
    resource_group_name  = "observal-tfstate-rg"
    storage_account_name = "observaltfstate"
    container_name       = "tfstate"
    key                  = "staging.terraform.tfstate"
  }
}
