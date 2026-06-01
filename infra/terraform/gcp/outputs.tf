# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

output "app_url" {
  description = "Public URL for the Observal install."
  value       = local.app_url
}

output "cloud_run_urls" {
  description = "Cloud Run service URLs."
  value = {
    api    = google_cloud_run_v2_service.api.uri
    web    = google_cloud_run_v2_service.web.uri
    worker = google_cloud_run_v2_service.worker.uri
  }
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL instance connection name (for Cloud SQL Proxy)."
  value       = google_sql_database_instance.postgres.connection_name
}

output "cloud_sql_private_ip" {
  description = "Cloud SQL private IP."
  value       = google_sql_database_instance.postgres.private_ip_address
  sensitive   = true
}

output "redis_host" {
  description = "Memorystore Redis host."
  value       = google_redis_instance.main.host
  sensitive   = true
}

output "data_host_internal_ip" {
  description = "GCE data host internal IP. Empty when clickhouse_mode = 'cloud'."
  value       = local.clickhouse_self_hosted ? google_compute_instance.data_host[0].network_interface[0].network_ip : ""
}

output "data_host_ssh_command" {
  description = "IAP SSH command to access data host."
  value       = local.clickhouse_self_hosted ? "gcloud compute ssh ${google_compute_instance.data_host[0].name} --zone=${var.region}-a --tunnel-through-iap" : ""
}

output "backups_bucket" {
  description = "GCS bucket for backups."
  value       = google_storage_bucket.backups.name
}

output "secret_names" {
  description = "Secret Manager secret names."
  value       = { for k, v in google_secret_manager_secret.app : k => v.secret_id }
}

output "init_job_run_command" {
  description = "Command to manually run the init/migrations job."
  value       = "gcloud run jobs execute ${google_cloud_run_v2_job.init.name} --region=${var.region}"
}

output "edition" {
  description = "Deployed edition."
  value       = local.effective_edition
  sensitive   = true
}
