# SPDX-FileCopyrightText: 2026 RAWx18 <rawx18.dev@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Smoke tests for the OSS-Fuzz targets under fuzz/.

Guards against the targets rotting when a parser is renamed or a seed corpus
stops being useful. Requires Atheris, which the fuzz targets import at module
scope; install it with ``pip install atheris`` or run ``make test-fuzz``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("atheris")
pytest.importorskip("hypothesis")

FUZZ_DIR = Path(__file__).resolve().parent.parent / "fuzz"

# Fuzz targets run as standalone scripts, so their own directory is the import root.
if str(FUZZ_DIR) not in sys.path:
    sys.path.insert(0, str(FUZZ_DIR))

# oss-fuzz/build.sh discovers targets with exactly this glob.
TARGETS = sorted(path.stem for path in FUZZ_DIR.glob("*_fuzzer.py"))
CORPUS_TARGETS = sorted(target for target in TARGETS if (FUZZ_DIR / "corpus" / target).is_dir())


def test_targets_are_discoverable():
    assert TARGETS, "no fuzz targets matched fuzz/*_fuzzer.py"


@pytest.mark.parametrize("target", TARGETS)
def test_target_exposes_an_entry_point(target):
    """Every target must be importable and expose the Atheris bootstrap."""
    module = importlib.import_module(target)
    assert callable(module.main)


@pytest.mark.parametrize("target", CORPUS_TARGETS)
def test_seed_corpus_is_within_the_input_bound(target):
    """Seeds larger than the target's cap are rejected before reaching any parser."""
    module = importlib.import_module(target)
    for seed in sorted((FUZZ_DIR / "corpus" / target).iterdir()):
        size = seed.stat().st_size
        assert 0 < size <= module._MAX_INPUT_BYTES, f"{seed.name} is {size} bytes"


@pytest.mark.parametrize("target", CORPUS_TARGETS)
def test_seed_corpus_runs_clean(target):
    """The committed corpus must not crash the target it seeds."""
    module = importlib.import_module(target)
    for seed in sorted((FUZZ_DIR / "corpus" / target).iterdir()):
        module.TestOneInput(seed.read_bytes())


def test_session_seeds_reach_every_parser():
    """The first byte of a session seed selects the harness.

    Anything that rewrites these files -- a licence header hook, an editor
    adding a BOM -- changes that byte and quietly points the whole corpus at a
    single parser, which costs most of the corpus' reach without failing a
    single test. Assert every registered parser still has a seed.
    """
    from observal_shared.harness_registry import HARNESS_REGISTRY

    session = importlib.import_module("_session")

    seed_dir = FUZZ_DIR / "corpus" / "session_jsonl_fuzzer"
    seeded = {session.HARNESSES[seed.read_bytes()[0] % len(session.HARNESSES)] for seed in seed_dir.iterdir()}

    reached = {HARNESS_REGISTRY[harness]["session_parser"] for harness in seeded}
    expected = {spec["session_parser"] for spec in HARNESS_REGISTRY.values() if spec["session_parser"]}
    assert reached == expected, f"no seed reaches {sorted(expected - reached)}"


def test_structured_session_property_holds():
    """Run the polyglot Hypothesis target as an ordinary property test."""
    module = importlib.import_module("session_structure_fuzzer")
    module.test_session_pipeline_contract()
