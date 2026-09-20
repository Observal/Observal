# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

# DuckDB is always self-hosted, so resources previously guarded by the
# clickhouse_self_hosted count move from indexed to singleton addresses. Keep
# these declarations permanently: removing them would make existing installs
# destroy and recreate the data host and its persistent volume.
moved {
  from = data.aws_ami.al2023[0]
  to   = data.aws_ami.al2023
}

moved {
  from = data.aws_subnet.data_host[0]
  to   = data.aws_subnet.data_host
}

moved {
  from = aws_ebs_volume.data[0]
  to   = aws_ebs_volume.data
}

moved {
  from = aws_network_interface.data_host[0]
  to   = aws_network_interface.data_host
}

moved {
  from = aws_instance.data_host[0]
  to   = aws_instance.data_host
}

moved {
  from = aws_volume_attachment.data[0]
  to   = aws_volume_attachment.data
}

moved {
  from = aws_route53_record.clickhouse_internal[0]
  to   = aws_route53_record.analytics_internal
}

moved {
  from = aws_security_group.data_host[0]
  to   = aws_security_group.data_host
}

moved {
  from = aws_iam_role.data_host[0]
  to   = aws_iam_role.data_host
}

moved {
  from = aws_iam_role_policy_attachment.data_host_ssm_core[0]
  to   = aws_iam_role_policy_attachment.data_host_ssm_core
}

moved {
  from = aws_iam_role_policy_attachment.data_host_cw_agent[0]
  to   = aws_iam_role_policy_attachment.data_host_cw_agent
}

moved {
  from = aws_iam_policy.data_host_ssm_read[0]
  to   = aws_iam_policy.data_host_ssm_read
}

moved {
  from = aws_iam_role_policy_attachment.data_host_ssm_read[0]
  to   = aws_iam_role_policy_attachment.data_host_ssm_read
}

moved {
  from = aws_iam_policy.data_host_backups[0]
  to   = aws_iam_policy.data_host_backups
}

moved {
  from = aws_iam_role_policy_attachment.data_host_backups[0]
  to   = aws_iam_role_policy_attachment.data_host_backups
}

moved {
  from = aws_iam_instance_profile.data_host[0]
  to   = aws_iam_instance_profile.data_host
}
