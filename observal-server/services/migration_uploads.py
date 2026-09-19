# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

"""Disk-backed temporary storage for large multipart migration uploads."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def configure_migration_upload_tempdir() -> Path | None:
    """Spool multipart migration uploads to persistent disk instead of tmpfs."""
    artifact_root = os.environ.get("MIGRATION_ARTIFACT_ROOT")
    if not artifact_root:
        return None
    upload_tempdir = Path(artifact_root).parent / "migration_upload_tmp"
    upload_tempdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(upload_tempdir, 0o700)
    tempfile.tempdir = str(upload_tempdir)
    return upload_tempdir
