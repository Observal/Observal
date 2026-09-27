# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "update_spdx_copyright", Path(__file__).parents[1] / "scripts" / "update_spdx_copyright.py"
)
spdx = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spdx)


def test_json_files_get_no_comment_header():
    # A "#" line in package.json breaks npm; JSON licensing lives in REUSE.toml.
    assert spdx.comment_prefix(Path("packages/pi-extension/package.json")) is None
    assert spdx.comment_prefix(Path("observal_cli/delegation/service.py")) == ("# ", "")
