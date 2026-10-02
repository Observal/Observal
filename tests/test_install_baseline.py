# SPDX-License-Identifier: Apache-2.0

"""Manual pulls establish an exact baseline; legacy or dirty installs cannot auto-update."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from observal_cli import install_baseline

REGISTRY = "https://example.test"
ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def isolated_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(install_baseline, "BASELINE_DIR", tmp_path / "baselines")


def kwargs(root: Path) -> dict:
    return {
        "registry": REGISTRY,
        "harness": "pi",
        "agent_id": ID,
        "scope": "user",
        "root": str(root),
        "version": "1.0.0",
        "lock_digest": "sha256:example",
    }


def test_no_adoption_and_manual_capture_of_file_and_directory(tmp_path: Path) -> None:
    root = tmp_path / "project"
    skill = root / "skills" / "reviewer"
    skill.mkdir(parents=True)
    file = skill / "SKILL.md"
    file.write_text("original")
    shared = root / "mcp.json"
    shared.write_text(json.dumps({"managed": "v1", "unmanaged": "mine"}))
    with pytest.raises(install_baseline.BaselineError):
        install_baseline.verified_files(**kwargs(root))
    install_baseline.capture(**kwargs(root), written_paths=[str(skill), str(shared)])
    assert len(install_baseline.verified_files(**kwargs(root))) == 2
    shared.write_text(json.dumps({"managed": "v1", "unmanaged": "changed"}))
    with pytest.raises(install_baseline.BaselineError, match="changed"):
        install_baseline.verified_files(**kwargs(root))
    shared.write_text(json.dumps({"managed": "v1", "unmanaged": "mine"}))
    (skill / "unexpected.txt").write_text("added")
    with pytest.raises(install_baseline.BaselineError, match="changed"):
        install_baseline.verified_files(**kwargs(root))


def test_shared_file_claim_is_not_silently_adopted(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    shared = root / "mcp.json"
    shared.write_text("{}")
    install_baseline.capture(**kwargs(root), written_paths=[str(shared)])
    with pytest.raises(install_baseline.BaselineError, match="shared"):
        install_baseline.capture(
            **{**kwargs(root), "agent_id": "33333333-3333-4333-8333-333333333333"},
            written_paths=[str(shared)],
        )
    assert install_baseline.verified_files(**kwargs(root))


def test_version_mismatch_missing_file_and_symlink_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    file = root / "AGENTS.md"
    file.write_text("managed")
    install_baseline.capture(**kwargs(root), written_paths=[str(file)])
    with pytest.raises(install_baseline.BaselineError):
        install_baseline.verified_files(**{**kwargs(root), "version": "2.0.0"})
    file.unlink()
    with pytest.raises(install_baseline.BaselineError):
        install_baseline.verified_files(**kwargs(root))
    target = root / "other"
    target.write_text("managed")
    file.symlink_to(target)
    with pytest.raises(install_baseline.BaselineError, match="symbolic link"):
        install_baseline.verified_files(**kwargs(root))
