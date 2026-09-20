# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

# DuckDB is always self-hosted, so resources previously guarded by the
# clickhouse_self_hosted count move from indexed to singleton addresses.
moved {
  from = google_service_account.data_host[0]
  to   = google_service_account.data_host
}

moved {
  from = google_project_iam_member.data_host_log_writer[0]
  to   = google_project_iam_member.data_host_log_writer
}

moved {
  from = google_project_iam_member.data_host_metric_writer[0]
  to   = google_project_iam_member.data_host_metric_writer
}

moved {
  from = google_project_iam_member.data_host_storage_admin[0]
  to   = google_project_iam_member.data_host_storage_admin
}

moved {
  from = google_compute_disk.data[0]
  to   = google_compute_disk.data
}

moved {
  from = google_compute_instance.data_host[0]
  to   = google_compute_instance.data_host
}
