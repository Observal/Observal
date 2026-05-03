"""Anonymize session data before passing to LLM prompts."""

from __future__ import annotations


def anonymize_sessions(sessions: list[dict]) -> list[dict]:
    """Replace user IDs with labels and truncate paths to repo names.

    Prevents leaking PII into LLM prompts while preserving cross-user patterns.
    """
    user_map: dict[str, str] = {}
    result = []

    for s in sessions:
        s = dict(s)  # Don't mutate original
        uid = s.get("user_id", "") or ""
        if uid and uid not in user_map:
            user_map[uid] = f"User {chr(65 + len(user_map) % 26)}"
        s["user_id"] = user_map.get(uid, "Unknown")

        # Truncate cwd to just the repo/directory name
        cwd = s.get("cwd", "") or ""
        if cwd:
            s["cwd"] = cwd.rstrip("/").split("/")[-1]

        # Truncate user_name to first name only
        name = s.get("user_name", "") or ""
        if name:
            s["user_name"] = name.split()[0] if " " in name else name

        result.append(s)

    return result
