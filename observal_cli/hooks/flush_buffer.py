#!/usr/bin/env python3
"""Flush up to 20 buffered telemetry events to the Observal server.

Called in the background by the shell hook after a successful curl.
No dependencies beyond Python stdlib (sqlite3, json, os, urllib).

Encrypted payloads (encrypted=1) are sent with
``X-Observal-Encrypted: ecies-p256`` and ``Content-Type: application/octet-stream``
so the server can decrypt before ingestion.
"""

import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

DB_PATH = Path.home() / ".observal" / "telemetry_buffer.db"
FLUSH_LIMIT = 20
MAX_RETRIES = 3


def main() -> None:
    hooks_url = os.environ.get("OBSERVAL_HOOKS_URL", "http://localhost:8000/api/v1/otel/hooks")
    user_id = os.environ.get("OBSERVAL_USER_ID", "")

    if not DB_PATH.exists():
        return

    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=3000")

        # Gracefully handle databases created before the encrypted column existed
        columns = {row[1] for row in conn.execute("PRAGMA table_info(pending_events)").fetchall()}
        has_encrypted_col = "encrypted" in columns

        if has_encrypted_col:
            rows = conn.execute(
                "SELECT id, payload, encrypted FROM pending_events "
                "WHERE status = 'pending' AND attempts < ? ORDER BY id ASC LIMIT ?",
                (MAX_RETRIES, FLUSH_LIMIT),
            ).fetchall()
        else:
            rows = [
                (r[0], r[1], 0)
                for r in conn.execute(
                    "SELECT id, payload FROM pending_events "
                    "WHERE status = 'pending' AND attempts < ? ORDER BY id ASC LIMIT ?",
                    (MAX_RETRIES, FLUSH_LIMIT),
                ).fetchall()
            ]

        if not rows:
            # Also clean up old sent events while we're here
            conn.execute(
                "DELETE FROM pending_events WHERE status = 'sent' AND created_at < datetime('now', '-24 hours')"
            )
            conn.commit()
            return

        sent_ids = []
        failed_ids = []

        for row_id, payload, encrypted in rows:
            try:
                if encrypted:
                    # Encrypted payload — send as raw bytes
                    data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
                    req = urllib.request.Request(
                        hooks_url,
                        data=data,
                        headers={"Content-Type": "application/octet-stream"},
                        method="POST",
                    )
                    req.add_header("X-Observal-Encrypted", "ecies-p256")
                else:
                    # Plaintext JSON payload
                    data = payload.encode("utf-8") if isinstance(payload, str) else payload
                    req = urllib.request.Request(
                        hooks_url,
                        data=data,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                if user_id:
                    req.add_header("X-Observal-User-Id", user_id)

                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status < 300:
                        # Verify the server actually ingested the event.
                        # The hook endpoint returns {"ingested": 0} on
                        # insert failure with HTTP 200 — treat that as a
                        # retryable failure so we don't lose events.
                        try:
                            body = resp.read()
                            import json as _json

                            result = _json.loads(body)
                            if result.get("ingested", 0) < 1:
                                failed_ids.append(row_id)
                                continue
                        except Exception:
                            pass
                        sent_ids.append(row_id)
                    else:
                        failed_ids.append(row_id)
            except Exception:
                failed_ids.append(row_id)

        if sent_ids:
            placeholders = ",".join("?" for _ in sent_ids)
            conn.execute(
                f"UPDATE pending_events SET status = 'sent', "
                f"last_attempt = datetime('now') WHERE id IN ({placeholders})",
                sent_ids,
            )

        if failed_ids:
            placeholders = ",".join("?" for _ in failed_ids)
            conn.execute(
                f"UPDATE pending_events SET attempts = attempts + 1, "
                f"last_attempt = datetime('now'), "
                f"status = CASE WHEN attempts + 1 >= {MAX_RETRIES} THEN 'failed' ELSE 'pending' END "
                f"WHERE id IN ({placeholders})",
                failed_ids,
            )

        conn.commit()

        # Clean up old sent events
        conn.execute("DELETE FROM pending_events WHERE status = 'sent' AND created_at < datetime('now', '-24 hours')")
        conn.commit()

    finally:
        conn.close()


if __name__ == "__main__":
    main()
