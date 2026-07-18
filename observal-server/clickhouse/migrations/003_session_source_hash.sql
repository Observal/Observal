# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

ALTER TABLE session_events ADD COLUMN IF NOT EXISTS source_sha256 String DEFAULT '' CODEC(ZSTD(1)) AFTER line_hash;
