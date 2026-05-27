# SPDX-FileCopyrightText: 2026 Yash Gadgil <yashgadgil08@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for SEC-003: TrustedProxyMiddleware.

The middleware replaces Uvicorn's --proxy-headers flag so that both
X-Forwarded-For (client IP) and X-Forwarded-Proto (scheme) are only
honoured from IPs listed in ``security.trusted_proxy_ips``.

Unlike Uvicorn (which takes the leftmost XFF entry), this middleware
walks XFF right-to-left and skips trusted proxy IPs, making it
resistant to spoofing. Supports both plain IPs and CIDR notation.
"""

from unittest.mock import patch

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from api.middleware.trusted_proxy import TrustedProxyMiddleware


def _make_app():
    """Build a minimal Starlette app with only TrustedProxyMiddleware."""

    async def info(request: Request):
        return JSONResponse(
            {
                "ip": request.client.host,  # pyright: ignore[reportOptionalMemberAccess]
                "scheme": request.scope["scheme"],
            }
        )

    app = Starlette(routes=[Route("/info", info)])
    app.add_middleware(TrustedProxyMiddleware)
    return app


# ---------------------------------------------------------------------------
# X-Forwarded-Proto tests
# ---------------------------------------------------------------------------


class TestProtoHandling:
    def test_untrusted_peer_proto_ignored(self):
        """X-Forwarded-Proto from a non-trusted peer is ignored."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = "10.0.0.1"
            resp = client.get("/info", headers={"X-Forwarded-Proto": "https"})
        assert resp.json()["scheme"] == "http"

    def test_trusted_peer_proto_applied(self):
        """X-Forwarded-Proto from a trusted peer sets the scheme to https."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = "testclient"
            resp = client.get("/info", headers={"X-Forwarded-Proto": "https"})
        assert resp.json()["scheme"] == "https"

    def test_no_trusted_proxies_proto_ignored(self):
        """When trusted proxy list is empty, X-Forwarded-Proto is always ignored."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = ""
            resp = client.get("/info", headers={"X-Forwarded-Proto": "https"})
        assert resp.json()["scheme"] == "http"

    def test_invalid_proto_value_rejected(self):
        """Only 'http' and 'https' are accepted; other values are ignored."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = "testclient"
            resp = client.get("/info", headers={"X-Forwarded-Proto": "ftp"})
        assert resp.json()["scheme"] == "http"


# ---------------------------------------------------------------------------
# X-Forwarded-For (client IP resolution) tests
# ---------------------------------------------------------------------------


class TestClientIpResolution:
    def test_untrusted_peer_xff_ignored(self):
        """XFF from a non-trusted peer does not change client IP."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = "10.0.0.1"
            resp = client.get("/info", headers={"X-Forwarded-For": "99.99.99.1"})
        # testclient is not trusted, XFF ignored
        assert resp.json()["ip"] == "testclient"

    def test_trusted_peer_rightmost_non_trusted_ip_used(self):
        """When peer is trusted, rightmost non-trusted IP from XFF is used."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = "testclient,10.0.0.2"
            resp = client.get(
                "/info",
                headers={"X-Forwarded-For": "5.5.5.5, 8.8.8.8, 10.0.0.2"},
            )
        # Reversed: 10.0.0.2 (trusted, skip), 8.8.8.8 (not trusted, use it)
        assert resp.json()["ip"] == "8.8.8.8"

    def test_spoofed_leftmost_ignored(self):
        """Attacker-controlled leftmost XFF entry is never used."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = "testclient"
            resp = client.get(
                "/info",
                headers={"X-Forwarded-For": "spoofed.ip, real.client.ip"},
            )
        # Reversed: real.client.ip (not trusted) -> used
        assert resp.json()["ip"] == "real.client.ip"

    def test_all_xff_trusted_keeps_peer_ip(self):
        """When all XFF IPs are trusted, client IP stays as the TCP peer."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = "testclient,10.0.0.1,10.0.0.2"
            resp = client.get(
                "/info",
                headers={"X-Forwarded-For": "10.0.0.1, 10.0.0.2"},
            )
        # All XFF IPs are trusted, no override happens
        assert resp.json()["ip"] == "testclient"

    def test_no_xff_header_keeps_peer_ip(self):
        """When no XFF header is sent, client IP is the TCP peer."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = "testclient"
            resp = client.get("/info")
        assert resp.json()["ip"] == "testclient"

    def test_empty_trusted_list_xff_ignored(self):
        """When no proxies are trusted, XFF cannot change client IP."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = ""
            resp = client.get(
                "/info",
                headers={"X-Forwarded-For": "99.99.99.1"},
            )
        assert resp.json()["ip"] == "testclient"

    def test_multiple_trusted_proxies_parsed(self):
        """Comma-separated trusted proxy list is parsed and whitespace trimmed."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = " testclient , 10.0.0.1 "
            resp = client.get(
                "/info",
                headers={"X-Forwarded-For": "203.0.113.50, 10.0.0.1"},
            )
        # Reversed: 10.0.0.1 (trusted, skip), 203.0.113.50 (not trusted, use)
        assert resp.json()["ip"] == "203.0.113.50"


# ---------------------------------------------------------------------------
# CIDR notation support
# ---------------------------------------------------------------------------


class TestCidrSupport:
    def test_cidr_matches_peer_ip(self):
        """A peer IP within a trusted CIDR range is recognized as trusted."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            # testclient is not a real IP, so trust the Docker-style subnet
            # that contains 127.0.0.1 (TestClient uses 'testclient' as host)
            mock_ds.get_sync.return_value = "testclient,172.16.0.0/12"
            resp = client.get(
                "/info",
                headers={"X-Forwarded-For": "203.0.113.99, 172.18.0.5"},
            )
        # 172.18.0.5 is in 172.16.0.0/12 (trusted, skip), 203.0.113.99 used
        assert resp.json()["ip"] == "203.0.113.99"

    def test_cidr_skips_xff_entries_in_range(self):
        """XFF entries within a trusted CIDR are skipped during right-to-left walk."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            mock_ds.get_sync.return_value = "testclient,10.0.0.0/8"
            resp = client.get(
                "/info",
                headers={"X-Forwarded-For": "82.1.2.3, 10.0.0.1, 10.0.0.2"},
            )
        # 10.0.0.2 trusted, 10.0.0.1 trusted, 82.1.2.3 not trusted
        assert resp.json()["ip"] == "82.1.2.3"

    def test_cidr_does_not_match_outside_range(self):
        """IPs outside the CIDR range are not considered trusted."""
        app = _make_app()
        client = TestClient(app)
        with patch("api.middleware.trusted_proxy.ds") as mock_ds:
            # Only 192.168.0.0/16 is trusted; testclient is not in that range
            mock_ds.get_sync.return_value = "192.168.0.0/16"
            resp = client.get(
                "/info",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )
        # testclient not trusted, XFF ignored
        assert resp.json()["ip"] == "testclient"

    def test_default_docker_cidr_trusts_nginx(self):
        """The default setting (172.16.0.0/12) matches typical Docker bridge IPs."""
        from services.shared.ip_utils import is_trusted, parse_trusted

        exact, networks = parse_trusted("172.16.0.0/12,10.0.0.0/8,192.168.0.0/16,127.0.0.1")
        # Typical Docker-assigned nginx IPs
        assert is_trusted("172.18.0.2", exact, networks)
        assert is_trusted("172.20.0.5", exact, networks)
        assert is_trusted("10.0.2.1", exact, networks)
        assert is_trusted("127.0.0.1", exact, networks)
        # Public IPs should NOT be trusted
        assert not is_trusted("8.8.8.8", exact, networks)
        assert not is_trusted("203.0.113.1", exact, networks)
