# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

output "app_url" {
  description = "Public URL for the Observal install."
  value       = module.observal.app_url
}

output "ecs_cluster_name" {
  value = module.observal.ecs_cluster_name
}

output "data_host_ssm_session_command" {
  description = "Open a shell on the data tier host."
  value       = module.observal.data_host_ssm_session_command
}

output "init_run_task_command" {
  description = "Re-run the migrations/seed task."
  value       = module.observal.init_run_task_command
}
