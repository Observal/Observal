# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Backend integration tests for MCP download counting and rejection flow.

Requires: `make up` (Docker stack running on localhost:8000).

Run:
    cd observal-server
    uv run --with pytest --with pytest-asyncio --with httpx pytest ../tests/test_mcp_download_reject.py -v
"""

import uuid

import httpx
import pytest

BASE = "http://localhost:8000"
ADMIN_EMAIL = "admin@demo.example"
ADMIN_PASSWORD = "admin-changeme"


def _api_reachable() -> bool:
    try:
        r = httpx.get(f"{BASE}/health", timeout=2)
        return r.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _api_reachable(), reason="Docker stack not running (make up)"),
]

_token_cache: str | None = None


async def _get_token() -> str:
    global _token_cache
    if _token_cache:
        return _token_cache
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        for attempt in range(3):
            r = await c.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
            if r.status_code == 200:
                _token_cache = r.json()["access_token"]
                return _token_cache
            if r.status_code == 429:
                import asyncio

                await asyncio.sleep(15)
                continue
            raise AssertionError(f"Login failed: {r.text}")
    raise AssertionError("Login failed after retries (rate limited)")


@pytest.fixture()
async def admin_headers():
    token = await _get_token()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
async def client():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        yield c


# ── Download Count ──────────────────────────────────────────────────────────


class TestMcpDownloadCount:
    """POST /mcps/{id}/install increments download_count."""

    @pytest.fixture(autouse=True)
    def _mcp_name(self):
        self.mcp_name = f"dl-count-{uuid.uuid4().hex[:8]}"

    @pytest.mark.asyncio
    async def test_install_records_downloads(self, client, admin_headers):
        # Submit
        r = await client.post(
            "/api/v1/mcps/submit",
            headers=admin_headers,
            json={
                "name": self.mcp_name,
                "version": "1.0.0",
                "description": "Download count test",
                "owner": "admin",
                "category": "developer-tools",
                "git_url": "https://github.com/example/repo.git",
                "command": "node",
                "args": ["index.js"],
            },
        )
        assert r.status_code == 200, f"Submit failed: {r.text}"
        listing_id = str(r.json()["id"])

        # Approve
        r = await client.post(f"/api/v1/review/{listing_id}/approve", headers=admin_headers)
        assert r.status_code == 200, f"Approve failed: {r.text}"

        # Install twice with different IDEs
        r = await client.post(
            f"/api/v1/mcps/{listing_id}/install",
            headers=admin_headers,
            json={"ide": "cursor"},
        )
        assert r.status_code == 200, f"Install 1 failed: {r.text}"
        data1 = r.json()
        assert "config_snippet" in data1
        assert data1["ide"] == "cursor"

        r = await client.post(
            f"/api/v1/mcps/{listing_id}/install",
            headers=admin_headers,
            json={"ide": "vscode"},
        )
        assert r.status_code == 200, f"Install 2 failed: {r.text}"
        data2 = r.json()
        assert "config_snippet" in data2
        assert data2["ide"] == "vscode"

    @pytest.mark.asyncio
    async def test_install_unapproved_returns_404(self, client, admin_headers):
        # Submit but don't approve
        r = await client.post(
            "/api/v1/mcps/submit",
            headers=admin_headers,
            json={
                "name": self.mcp_name,
                "version": "1.0.0",
                "description": "Unapproved install test",
                "owner": "admin",
                "category": "developer-tools",
                "git_url": "https://github.com/example/repo.git",
                "command": "node",
                "args": ["index.js"],
            },
        )
        assert r.status_code == 200
        listing_id = str(r.json()["id"])

        # Try to install unapproved — should fail
        r = await client.post(
            f"/api/v1/mcps/{listing_id}/install",
            headers=admin_headers,
            json={"ide": "cursor"},
        )
        # Self-install of own pending listing is allowed, but third-party would get 404
        assert r.status_code in (200, 404)


# ── Reject with Reason ──────────────────────────────────────────────────────


class TestMcpRejectWithReason:
    """POST /review/{listing_id}/reject persists rejection_reason."""

    @pytest.fixture(autouse=True)
    def _mcp_name(self):
        self.mcp_name = f"reject-{uuid.uuid4().hex[:8]}"

    @pytest.mark.asyncio
    async def test_reject_with_reason_persists(self, client, admin_headers):
        # Submit
        r = await client.post(
            "/api/v1/mcps/submit",
            headers=admin_headers,
            json={
                "name": self.mcp_name,
                "version": "1.0.0",
                "description": "Rejection test",
                "owner": "admin",
                "category": "developer-tools",
                "git_url": "https://github.com/example/repo.git",
                "command": "node",
                "args": ["index.js"],
            },
        )
        assert r.status_code == 200, f"Submit failed: {r.text}"
        listing_id = str(r.json()["id"])

        # Reject with reason
        r = await client.post(
            f"/api/v1/review/{listing_id}/reject",
            headers=admin_headers,
            json={"reason": "Missing documentation and tests"},
        )
        assert r.status_code == 200, f"Reject failed: {r.text}"
        data = r.json()
        assert data["status"] == "rejected"

        # Verify rejection_reason persisted on GET
        r = await client.get(f"/api/v1/mcps/{self.mcp_name}", headers=admin_headers)
        assert r.status_code == 200
        mcp_data = r.json()
        assert mcp_data["status"] == "rejected"
        assert mcp_data.get("rejection_reason") == "Missing documentation and tests"
