# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

output "app_url" {
  value = module.observal.app_url
}

output "cloud_run_urls" {
  value = module.observal.cloud_run_urls
}

output "init_job_run_command" {
  value = module.observal.init_job_run_command
}

output "data_host_ssh_command" {
  value = module.observal.data_host_ssh_command
}
