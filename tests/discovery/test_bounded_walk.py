# SPDX-FileCopyrightText: 2026 Observal Contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import TYPE_CHECKING

from observal_cli.discovery.adapter_support import RichAdapterScanner
from observal_cli.discovery.bounded_walk import AggregateDiscoveryBudget, BoundedWalker, WalkLimits
from observal_cli.discovery.models import DiagnosticCode, DiscoveryScope

if TYPE_CHECKING:
    from pathlib import Path


def _codes(walker: BoundedWalker) -> list[DiagnosticCode]:
    return [item.code for item in walker.diagnostics]


def test_walk_is_deterministic_and_does_not_follow_directory_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "z").mkdir(parents=True)
    (root / "a").mkdir()
    (root / "z" / "SKILL.md").write_text("z")
    (root / "a" / "SKILL.md").write_text("a")
    (root / "linked-dir").symlink_to(root / "z", target_is_directory=True)

    walker = BoundedWalker(root, provider="test")

    assert [path.parent.name for path in walker.files(root, name="SKILL.md")] == ["a", "z"]


def test_file_symlinks_must_resolve_inside_approved_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "inside.json"
    inside.write_text("{}")
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (root / "safe.json").symlink_to(inside)
    (root / "escape.json").symlink_to(outside)

    walker = BoundedWalker(root, provider="test")
    paths = list(walker.files(root, suffix=".json"))

    assert [path.name for path in paths] == ["inside.json", "safe.json"]
    assert DiagnosticCode.SYMLINK_ESCAPE in _codes(walker)


def test_size_and_file_limits_preserve_partial_results(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("ok")
    (root / "b.txt").write_text("too large")
    deep = root
    for index in range(4):
        deep = deep / str(index)
        deep.mkdir()
    (deep / "deep.txt").write_text("deep")

    size_walker = BoundedWalker(root, provider="test", limits=WalkLimits(max_file_bytes=3))
    assert size_walker.read_text(root / "a.txt") == "ok"
    assert size_walker.read_text(root / "b.txt") is None
    assert DiagnosticCode.METADATA_TOO_LARGE in _codes(size_walker)

    limited = BoundedWalker(root, provider="test", limits=WalkLimits(max_files_per_root=2))
    assert list(limited.files(root, suffix=".txt"))
    assert DiagnosticCode.ITEM_LIMIT_REACHED in _codes(limited)


def test_depth_limit_stops_deep_metadata(tmp_path: Path) -> None:
    root = tmp_path / "root"
    deep = root
    for index in range(4):
        deep = deep / str(index)
        deep.mkdir(parents=True)
    (deep / "deep.json").write_text("{}")
    walker = BoundedWalker(root, provider="test", limits=WalkLimits(max_depth=2))

    assert list(walker.files(root, suffix=".json")) == []
    assert DiagnosticCode.RECURSION_LIMIT_REACHED in _codes(walker)


def test_aggregate_root_limit_emits_one_stable_diagnostic(tmp_path: Path) -> None:
    budget = AggregateDiscoveryBudget(max_roots=1)
    first = BoundedWalker(tmp_path / "one", provider="test", budget=budget)
    second = BoundedWalker(tmp_path / "two", provider="test", budget=budget)
    third = BoundedWalker(tmp_path / "three", provider="test", budget=budget)

    assert not first.stopped
    assert second.stopped and third.stopped
    diagnostics = second.diagnostics + third.diagnostics
    assert [item.code for item in diagnostics] == [DiagnosticCode.APPROVED_ROOT_LIMIT_REACHED]


def test_aggregate_file_and_evidence_limits_emit_single_diagnostics(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.json").write_text("{}")
    (root / "b.json").write_text("{}")
    file_budget = AggregateDiscoveryBudget(max_files=1)
    first = BoundedWalker(root, provider="test", budget=file_budget)
    second = BoundedWalker(root, provider="test", budget=file_budget)
    list(first.files(root))
    list(second.files(root))
    file_diagnostics = first.diagnostics + second.diagnostics
    assert [item.code for item in file_diagnostics].count(DiagnosticCode.COLLECTION_FILE_LIMIT_REACHED) == 1

    evidence_budget = AggregateDiscoveryBudget(max_evidence=1)
    scanner = RichAdapterScanner(
        harness="test",
        scope=DiscoveryScope.PROJECT,
        root=root,
        project_dir=root,
        budget=evidence_budget,
    )
    scanner.add_agent_document(root / "a.json", name="one")
    scanner.add_agent_document(root / "b.json", name="two")
    result = scanner.finish()
    assert len(result.evidence) == 1
    assert [item.code for item in result.diagnostics].count(DiagnosticCode.EVIDENCE_LIMIT_REACHED) == 1


def test_deadline_stops_traversal_with_diagnostic(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "item.json").write_text("{}")
    ticks = iter([0.0, 2.0, 2.0])
    walker = BoundedWalker(
        root,
        provider="test",
        limits=WalkLimits(adapter_deadline_seconds=1),
        clock=lambda: next(ticks),
    )

    assert list(walker.files(root)) == []
    assert _codes(walker) == [DiagnosticCode.ADAPTER_DEADLINE_EXCEEDED]
