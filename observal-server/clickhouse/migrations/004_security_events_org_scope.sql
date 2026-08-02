# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

ALTER TABLE security_events ADD COLUMN IF NOT EXISTS org_id String DEFAULT '';
ALTER TABLE security_events ADD INDEX IF NOT EXISTS idx_security_events_org_id org_id TYPE bloom_filter(0.01) GRANULARITY 1;
