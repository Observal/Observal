# SPDX-FileCopyrightText: 2026 SrihariLegend <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Exercise the shipped Cordis plugin's durability boundary without a dsh build."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from observal_cli import deepseek_plugin


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_collector_runs_only_after_native_flush(tmp_path: Path):
    calls = tmp_path / "calls.jsonl"
    python = tmp_path / "fake-python"
    python.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "with open(os.environ['OBS_FAKE_CALLS'], 'a') as fp:\n"
        "    fp.write(json.dumps({'args':sys.argv[1:], 'dsh_home':os.environ['DSH_HOME']})+'\\n')\n"
    )
    python.chmod(0o700)
    script = """
import { pathToFileURL } from 'node:url';
import { readFileSync, existsSync } from 'node:fs';
const { apply } = await import(pathToFileURL(process.argv[1]).href);
let listener, dispose, release, started;
const flushStarted = new Promise(resolve => { started = resolve });
const ctx = {
  logger: { warn(message) { throw new Error(message) } },
  sessions: { flush() { started(); return new Promise(resolve => { release = resolve }) } },
  on(event, callback) { if (event === 'session/event') listener = callback },
  effect(callback) { dispose = callback() },
};
apply(ctx, { pythonPath: process.argv[2], dshHome: process.argv[3] });
const session = { id: 'session-check', header: { cwd: '/work/tree' } };
listener(session, { type: 'turn/start' });
listener(session, { type: 'turn/end' });
await flushStarted;
await new Promise(resolve => setTimeout(resolve, 300));
const before = existsSync(process.env.OBS_FAKE_CALLS) ? readFileSync(process.env.OBS_FAKE_CALLS, 'utf8') : '';
if (before.includes('session-check')) throw new Error('collection ran before flush');
console.log('BEFORE_FLUSH');
release(true);
await dispose();
console.log('AFTER_FLUSH');
"""
    env = {**os.environ, "OBS_FAKE_CALLS": str(calls)}
    deepseek_plugin.install(home=tmp_path)
    process = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(deepseek_plugin.plugin_path(tmp_path)),
            str(python),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
        env=env,
    )
    assert process.stdout.splitlines() == ["BEFORE_FLUSH", "AFTER_FLUSH"]
    entries = [json.loads(line) for line in calls.read_text().splitlines()]
    assert entries == [
        {"args": ["-m", "observal_cli.sessions.deepseek_collector", "--recover"], "dsh_home": str(tmp_path)},
        {
            "args": [
                "-m",
                "observal_cli.sessions.deepseek_collector",
                "--session-id",
                "session-check",
                "--cwd",
                "/work/tree",
            ],
            "dsh_home": str(tmp_path),
        },
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_collector_failure_does_not_interrupt_deepseek(tmp_path: Path):
    deepseek_plugin.install(home=tmp_path)
    script = """
import { pathToFileURL } from 'node:url';
const { apply } = await import(pathToFileURL(process.argv[1]).href);
let listener, dispose;
const warnings = [];
apply({
  logger: { warn(message) { warnings.push(message) } },
  sessions: { async flush() { return true } },
  on(event, callback) { listener = callback },
  effect(callback) { dispose = callback() },
}, { pythonPath: '/bin/false', dshHome: process.argv[2] });
listener({ id: 'session-failed', header: { cwd: '/work' } }, { type: 'turn/end' });
await dispose();
if (!warnings.some(message => message.includes('session-failed'))) throw new Error('failure was not reported');
console.log('continued');
"""
    process = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(deepseek_plugin.plugin_path(tmp_path)), str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert process.stdout.strip() == "continued"


def test_interrupted_first_install_is_recovered(tmp_path: Path):
    """A crash between the executable and its manifest must stay recoverable."""
    path = deepseek_plugin.plugin_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A first install publishes the executable, then dies before the ownership
    # manifest is written: the file exists but looks unmanaged.
    path.write_text(deepseek_plugin.plugin_source(), encoding="utf-8")

    assert not deepseek_plugin._manifest(tmp_path).exists()
    assert deepseek_plugin.status(tmp_path) == "stale"
    assert deepseek_plugin.install(home=tmp_path) is True
    assert deepseek_plugin.status(tmp_path) == "current"
    assert deepseek_plugin.install(home=tmp_path) is False
    # A file that was already byte-identical is not worth backing up.
    assert list(path.parent.glob("collector.mjs.bak*")) == []


def test_orphaned_plugin_can_be_cleaned_up(tmp_path: Path):
    """Cleanup must be able to remove the executable it published."""
    path = deepseek_plugin.plugin_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(deepseek_plugin.plugin_source(), encoding="utf-8")

    assert deepseek_plugin.remove(home=tmp_path) is True
    assert not path.exists()
    assert not deepseek_plugin._manifest(tmp_path).exists()


def test_foreign_file_at_the_plugin_path_is_never_claimed(tmp_path: Path):
    """Only a byte-identical copy of our own source may be adopted."""
    path = deepseek_plugin.plugin_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// someone else's plugin\n", encoding="utf-8")

    assert deepseek_plugin.status(tmp_path) == "unmanaged"
    with pytest.raises(ValueError):
        deepseek_plugin.install(home=tmp_path)
    assert deepseek_plugin.remove(home=tmp_path) is False
    assert path.read_text(encoding="utf-8") == "// someone else's plugin\n"
