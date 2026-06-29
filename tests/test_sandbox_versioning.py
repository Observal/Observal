# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import pytest
from fastapi import HTTPException


def test_sandbox_version_extra_accepts_runtime_fields():
    from services.component_version_extras import validate_and_extract

    extra = {
        "runtime_type": "docker",
        "image": "python:3.12-slim",
        "resource_limits": {"timeout": 60},
        "network_policy": "none",
        "entrypoint": "pytest",
        "runtime_config": {},
        "source_url": "https://github.com/acme/sandboxes",
        "source_ref": "main",
        "resolved_sha": "a" * 40,
        "sandbox_path": "sandboxes/python",
    }

    assert validate_and_extract("sandbox", extra) == extra


def test_sandbox_version_extra_rejects_firecracker_without_config():
    from services.component_version_extras import validate_and_extract

    with pytest.raises(HTTPException) as exc:
        validate_and_extract("sandbox", {"runtime_type": "firecracker", "image": "fc"})

    assert exc.value.status_code == 422
    assert "Firecracker" in exc.value.detail
