# SPDX-FileCopyrightText: 2026 Apoorv Garg <apoorvgarg.21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

moved {
  from = aws_vpc.main[0]
  to   = module.vpc[0].aws_vpc.main
}

moved {
  from = aws_internet_gateway.main[0]
  to   = module.vpc[0].aws_internet_gateway.main
}

moved {
  from = aws_subnet.public[0]
  to   = module.vpc[0].aws_subnet.public[0]
}

moved {
  from = aws_subnet.public[1]
  to   = module.vpc[0].aws_subnet.public[1]
}

moved {
  from = aws_subnet.private[0]
  to   = module.vpc[0].aws_subnet.private[0]
}

moved {
  from = aws_subnet.private[1]
  to   = module.vpc[0].aws_subnet.private[1]
}

moved {
  from = aws_eip.nat[0]
  to   = module.vpc[0].aws_eip.nat
}

moved {
  from = aws_nat_gateway.main[0]
  to   = module.vpc[0].aws_nat_gateway.main
}

moved {
  from = aws_route_table.public[0]
  to   = module.vpc[0].aws_route_table.public
}

moved {
  from = aws_route_table.private[0]
  to   = module.vpc[0].aws_route_table.private
}

moved {
  from = aws_route_table_association.public[0]
  to   = module.vpc[0].aws_route_table_association.public[0]
}

moved {
  from = aws_route_table_association.public[1]
  to   = module.vpc[0].aws_route_table_association.public[1]
}

moved {
  from = aws_route_table_association.private[0]
  to   = module.vpc[0].aws_route_table_association.private[0]
}

moved {
  from = aws_route_table_association.private[1]
  to   = module.vpc[0].aws_route_table_association.private[1]
}

moved {
  from = aws_cloudwatch_log_group.flow_logs
  to   = module.vpc[0].aws_cloudwatch_log_group.flow_logs[0]
}

moved {
  from = data.aws_iam_policy_document.flow_logs_assume[0]
  to   = module.vpc[0].data.aws_iam_policy_document.flow_logs_assume[0]
}

moved {
  from = data.aws_iam_policy_document.flow_logs_publish[0]
  to   = module.vpc[0].data.aws_iam_policy_document.flow_logs_publish[0]
}

moved {
  from = aws_iam_role.flow_logs[0]
  to   = module.vpc[0].aws_iam_role.flow_logs[0]
}

moved {
  from = aws_iam_role_policy.flow_logs[0]
  to   = module.vpc[0].aws_iam_role_policy.flow_logs[0]
}

moved {
  from = aws_flow_log.main[0]
  to   = module.vpc[0].aws_flow_log.main[0]
}
