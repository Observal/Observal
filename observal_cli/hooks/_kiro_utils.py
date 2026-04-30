#!/usr/bin/env python3
"""Shared utilities for Kiro hook scripts.

Internal module — not part of the public API.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import ctypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_char * 260),
        ]


def _get_parent_pid(pid: int) -> int | None:
    """Return the parent PID of *pid*, or None on failure."""
    if sys.platform == "linux":
        try:
            with open(f"/proc/{pid}/stat", "rb") as f:
                stat = f.read().decode(errors="ignore")
            rpar = stat.rfind(")")
            parts = stat[rpar + 2 :].split()
            return int(parts[1])
        except Exception:
            return None
    elif sys.platform == "darwin":
        import subprocess

        try:
            out = subprocess.check_output(["ps", "-p", str(pid), "-o", "ppid="], text=True, timeout=2).strip()
            return int(out)
        except Exception:
            return None
    elif sys.platform == "win32":
        h = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h == -1:
            return None
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if ctypes.windll.kernel32.Process32First(h, ctypes.byref(entry)):
                while True:
                    if entry.th32ProcessID == pid:
                        return entry.th32ParentProcessID
                    if not ctypes.windll.kernel32.Process32Next(h, ctypes.byref(entry)):
                        break
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
        return None
    return None


def _is_kiro_cli_process(pid: int) -> bool:
    """Return True if *pid* is a kiro-cli process (exact binary name check)."""
    if sys.platform == "linux":
        try:
            with open(f"/proc/{pid}/stat", "rb") as f:
                stat = f.read()
            start = stat.find(b"(") + 1
            end = stat.rfind(b")")
            comm = stat[start:end].decode(errors="ignore")
            return "kiro-cli" in comm
        except Exception:
            return False
    elif sys.platform == "darwin":
        import subprocess

        try:
            out = subprocess.check_output(["ps", "-p", str(pid), "-o", "comm="], text=True, timeout=2).strip()
            return "kiro-cli" in out
        except Exception:
            return False
    elif sys.platform == "win32":
        h = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h == -1:
            return False
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            if ctypes.windll.kernel32.Process32First(h, ctypes.byref(entry)):
                while True:
                    if entry.th32ProcessID == pid:
                        exe = entry.szExeFile.decode(errors="ignore").lower()
                        return "kiro-cli" in exe
                    if not ctypes.windll.kernel32.Process32Next(h, ctypes.byref(entry)):
                        break
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
        return False
    return False


def _find_kiro_cli_pid() -> int | None:
    """Walk up the process tree to find the kiro-cli process PID."""
    current = os.getpid()
    for _ in range(20):
        ppid = _get_parent_pid(current)
        if ppid is None or ppid <= 1:
            break
        if _is_kiro_cli_process(ppid):
            return ppid
        current = ppid
    return None


def _resolve_hooks_url() -> str:
    """Read hooks URL from config file when no --url is provided."""
    cfg_path = Path.home() / ".observal" / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            server = cfg.get("server_url", "")
            if server:
                return f"{server.rstrip('/')}/api/v1/telemetry/hooks"
        except Exception:
            pass
    return ""
