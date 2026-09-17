# SPDX-FileCopyrightText: 2026 Observal contributors
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""The SPDX pre-commit hook must stay out of code that generates SPDX text.

Several tooling files (release manifests, package notices) mention
``SPDX-FileCopyrightText`` inside string literals. Injecting a comment there
corrupts the source and breaks ``ruff format --check`` in CI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def hook():
    spec = importlib.util.spec_from_file_location(
        "update_spdx_copyright", REPO_ROOT / "scripts" / "update_spdx_copyright.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generator_file(tmp_path: Path) -> Path:
    path = tmp_path / "writer.py"
    # REUSE-IgnoreStart
    path.write_text(
        "# SPDX-FileCopyrightText: 2026 Original Author <original@example.com>\n"
        "# SPDX-License-Identifier: Apache-2.0\n"
        "\n"
        "def write_manifest(path):\n"
        "    path.write_text(\n"
        '        "# SPDX-FileCopyrightText: 2026 Original Author <original@example.com>\\n"\n'
        '        "# SPDX-License-Identifier: Apache-2.0\\n"\n'
        "    )\n"
    )
    # REUSE-IgnoreEnd
    return path


def test_injects_into_the_header_not_the_generated_template(hook, tmp_path):
    path = _generator_file(tmp_path)
    text_before = path.read_text()
    body_before = text_before[text_before.index("def write_manifest(") :]

    hook.inject_copyright(path, "New Committer", "new@example.com", 2026)

    text_after = path.read_text()
    lines = text_after.splitlines()
    assert lines[0] == "# SPDX-FileCopyrightText: 2026 Original Author <original@example.com>"
    assert lines[1] == "# SPDX-FileCopyrightText: 2026 New Committer <new@example.com>"
    # REUSE-IgnoreStart
    assert lines[2] == "# SPDX-License-Identifier: Apache-2.0"
    # REUSE-IgnoreEnd
    assert text_after[text_after.index("def write_manifest(") :] == body_before, (
        "the generated template must not be touched"
    )


def test_skips_files_whose_header_has_no_copyright_line(hook, tmp_path):
    path = tmp_path / "script.py"
    # REUSE-IgnoreStart
    original = 'BANNER = "# SPDX-FileCopyrightText: 2026 Someone <someone@example.com>"\n'
    # REUSE-IgnoreEnd
    path.write_text(original)

    hook.inject_copyright(path, "New Committer", "new@example.com", 2026)

    assert path.read_text() == original


def test_header_block_ends_at_first_statement(hook):
    lines = ["# comment\n", "\n", "# another\n", "import os\n", "# body\n"]
    assert hook._header_block_end(lines, "# ") == 3


# REUSE-IgnoreStart
@pytest.mark.parametrize(
    ("filename", "content"),
    [
        (
            "_helpers.tpl",
            "{{/*\n"
            "SPDX-FileCopyrightText: 2026 Original Author <original@example.com>\n"
            "*/}}\n"
            '{{- define "observal.name" -}}\n',
        ),
        (
            "001_baseline.sql",
            "-- SPDX-FileCopyrightText: 2026 Original Author <original@example.com>\n"
            "-- SPDX-License-Identifier: Apache-2.0\n"
            "CREATE TABLE t (a INTEGER);\n",
        ),
        (
            "model.json.license",
            "SPDX-FileCopyrightText: 2026 Original Author <original@example.com>\n"
            "SPDX-License-Identifier: Apache-2.0\n",
        ),
    ],
)
# REUSE-IgnoreEnd
def test_injects_into_headers_the_extension_prefix_cannot_parse(hook, tmp_path, filename, content):
    """Helm/SQL/license headers must not be skipped just because they differ."""
    path = tmp_path / filename
    path.write_text(content)

    hook.inject_copyright(path, "New Committer", "new@example.com", 2026)

    lines = path.read_text().splitlines()
    inserted = [i for i, line in enumerate(lines) if "New Committer" in line]
    assert inserted, "the committer's copyright line was not added"
    original = [i for i, line in enumerate(lines) if "2026 Original Author" in line]
    assert inserted[0] == original[0] + 1
