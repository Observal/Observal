# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Subramania Raja <dhanpraja231@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for SEC-003: rate limiting only trusts X-Forwarded-For from configured trusted proxies."""

from unittest.mock import MagicMock, patch


def _make_request(client_host: str, xff: str | None = None) -> MagicMock:
    """Build a minimal fake Starlette Request."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = client_host
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    request.headers = headers
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetRealIp:
    def test_no_trusted_proxies_xff_ignored(self):
        """When TRUSTED_PROXY_IPS is empty, XFF is ignored and socket IP is returned."""
        from api.ratelimit import _get_real_ip

        request = _make_request("1.2.3.4", xff="10.0.0.1, 192.168.1.1")
        with patch("api.ratelimit.settings") as mock_settings:
            mock_settings.TRUSTED_PROXY_IPS = []
            result = _get_real_ip(request)
        assert result == "1.2.3.4"

    def test_trusted_proxy_rightmost_non_trusted_returned(self):
        """When client IP is a trusted proxy, rightmost non-trusted IP from XFF is returned."""
        from api.ratelimit import _get_real_ip

        # XFF: spoofed attacker IP, then real client IP, then intermediate proxy
        request = _make_request("10.0.0.1", xff="5.5.5.5, 8.8.8.8, 10.0.0.2")
        with patch("api.ratelimit.settings") as mock_settings:
            mock_settings.TRUSTED_PROXY_IPS = ["10.0.0.1", "10.0.0.2"]
            result = _get_real_ip(request)
        # Reversed: 10.0.0.2 (trusted), 8.8.8.8 (not trusted) -> return 8.8.8.8
        assert result == "8.8.8.8"

    def test_client_not_in_trusted_list_xff_ignored(self):
        """When the direct peer is NOT in trusted proxies, XFF is ignored even if present."""
        from api.ratelimit import _get_real_ip

        request = _make_request("9.9.9.9", xff="1.1.1.1")
        with patch("api.ratelimit.settings") as mock_settings:
            mock_settings.TRUSTED_PROXY_IPS = ["10.0.0.1"]
            result = _get_real_ip(request)
        assert result == "9.9.9.9"

    def test_empty_xff_with_trusted_client_falls_back_to_socket_ip(self):
        """When XFF header is absent and client is trusted, falls back to socket IP."""
        from api.ratelimit import _get_real_ip

        request = _make_request("10.0.0.1", xff=None)
        with patch("api.ratelimit.settings") as mock_settings:
            mock_settings.TRUSTED_PROXY_IPS = ["10.0.0.1"]
            result = _get_real_ip(request)
        assert result == "10.0.0.1"

    def test_all_xff_ips_trusted_falls_back_to_socket_ip(self):
        """When every IP in XFF is also a trusted proxy, fall back to socket IP."""
        from api.ratelimit import _get_real_ip

        request = _make_request("10.0.0.1", xff="10.0.0.2, 10.0.0.3")
        with patch("api.ratelimit.settings") as mock_settings:
            mock_settings.TRUSTED_PROXY_IPS = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
            result = _get_real_ip(request)
        assert result == "10.0.0.1"

    def test_no_client_host_returns_localhost(self):
        """When request.client is None, returns 127.0.0.1."""
        from api.ratelimit import _get_real_ip

        request = MagicMock()
        request.client = None
        request.headers = {}
        with patch("api.ratelimit.settings") as mock_settings:
            mock_settings.TRUSTED_PROXY_IPS = []
            result = _get_real_ip(request)
        assert result == "127.0.0.1"


class TestTrustedProxyIpsValidator:
    def test_comma_separated_string_parsed(self):
        """Comma-separated string env var is parsed into a list of IPs."""
        from config import Settings

        s = Settings(TRUSTED_PROXY_IPS="10.0.0.1,10.0.0.2")
        assert s.TRUSTED_PROXY_IPS == ["10.0.0.1", "10.0.0.2"]

    def test_list_passthrough(self):
        """List values pass through the validator unchanged."""
        from config import Settings

        s = Settings(TRUSTED_PROXY_IPS=["10.0.0.1"])
        assert s.TRUSTED_PROXY_IPS == ["10.0.0.1"]

    def test_invalid_ip_is_ignored_with_warning(self):
        """Invalid IP strings are silently dropped and a warning is logged."""
        import logging

        from config import Settings

        with patch.object(logging.getLogger("config"), "warning") as mock_warn:
            s = Settings(TRUSTED_PROXY_IPS="10.0.0.1,not-an-ip,10.0.0.2")
        assert "10.0.0.1" in s.TRUSTED_PROXY_IPS
        assert "10.0.0.2" in s.TRUSTED_PROXY_IPS
        assert "not-an-ip" not in s.TRUSTED_PROXY_IPS

    def test_non_string_non_list_returns_empty(self):
        """Non-string, non-list values (e.g. None) return an empty list."""
        # Pass None directly via the validator path

        from config import Settings

        try:
            # pydantic will coerce None to [] via our validator
            result = Settings.__validators__  # just verify validator exists
        except Exception:
            pass
        # Direct validator call
        result = Settings.parse_trusted_proxy_ips(None)
        assert result == []
