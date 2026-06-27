# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Tests for alert evaluation engine, SSRF protection, and webhook delivery."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestIsPrivateUrl:
    def test_localhost_is_private(self):
        from services.alert_evaluator import is_private_url

        assert is_private_url("http://localhost:8080/hook") is True

    def test_127_0_0_1_is_private(self):
        from services.alert_evaluator import is_private_url

        assert is_private_url("http://127.0.0.1:9000/callback") is True

    def test_10_x_is_private(self):
        from services.alert_evaluator import is_private_url

        assert is_private_url("http://10.0.0.5/hook") is True

    def test_172_16_x_is_private(self):
        from services.alert_evaluator import is_private_url

        assert is_private_url("http://172.16.0.1/webhook") is True

    def test_192_168_x_is_private(self):
        from services.alert_evaluator import is_private_url

        assert is_private_url("http://192.168.1.100:5000/alert") is True

    def test_ipv6_loopback_is_private(self):
        from services.alert_evaluator import is_private_url

        assert is_private_url("http://[::1]:8080/hook") is True

    def test_link_local_is_private(self):
        from services.alert_evaluator import is_private_url

        assert is_private_url("http://169.254.169.254/latest/meta-data/") is True

    def test_public_ip_is_not_private(self):
        from services.alert_evaluator import is_private_url

        assert is_private_url("http://8.8.8.8/webhook") is False

    def test_public_domain_is_not_private(self):
        from services.alert_evaluator import is_private_url

        with patch("services.ssrf_guard.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
            assert is_private_url("https://example.com/webhook") is False

    def test_no_hostname_is_private(self):
        from services.alert_evaluator import is_private_url

        assert is_private_url("not-a-url") is True

    def test_dns_failure_is_private(self):
        from services.alert_evaluator import is_private_url

        with patch(
            "services.ssrf_guard.socket.getaddrinfo",
            side_effect=OSError("DNS failed"),
        ):
            assert is_private_url("http://nonexistent.invalid/hook") is True


class TestConditionMet:
    def test_above_met(self):
        from services.alert_evaluator import _condition_met

        assert _condition_met("above", 0.15, 0.10) is True

    def test_above_not_met(self):
        from services.alert_evaluator import _condition_met

        assert _condition_met("above", 0.05, 0.10) is False

    def test_below_met(self):
        from services.alert_evaluator import _condition_met

        assert _condition_met("below", 0.05, 0.10) is True

    def test_below_not_met(self):
        from services.alert_evaluator import _condition_met

        assert _condition_met("below", 0.15, 0.10) is False

    def test_unknown_condition(self):
        from services.alert_evaluator import _condition_met

        assert _condition_met("equal", 0.10, 0.10) is False


class TestQueryMetric:
    @pytest.mark.asyncio
    async def test_dispatches_error_rate(self):
        from services.alert_evaluator import _query_metric

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "0.05\n"
        with patch(
            "services.alert_evaluator._query",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await _query_metric("error_rate", "agent", "agent-1", 5)
        assert result == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_dispatches_latency_p99(self):
        from services.alert_evaluator import _query_metric

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "250.5\n"
        with patch(
            "services.alert_evaluator._query",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await _query_metric("latency_p99", "mcp", "mcp-1", 5)
        assert result == pytest.approx(250.5)

    @pytest.mark.asyncio
    async def test_dispatches_token_usage(self):
        from services.alert_evaluator import _query_metric

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "50000\n"
        with patch(
            "services.alert_evaluator._query",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await _query_metric("token_usage", "all", "", 5)
        assert result == pytest.approx(50000.0)

    @pytest.mark.asyncio
    async def test_unknown_metric_returns_none(self):
        from services.alert_evaluator import _query_metric

        result = await _query_metric("unknown_metric", "all", "", 5)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_response_returns_none(self):
        from services.alert_evaluator import _query_metric

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = ""
        with patch(
            "services.alert_evaluator._query",
            new_callable=AsyncMock,
            return_value=mock_resp,
        ):
            result = await _query_metric("error_rate", "all", "", 5)
        assert result is None


class TestDeliverWebhook:
    @pytest.mark.asyncio
    async def test_successful_delivery(self):
        from services.alert_evaluator import _deliver_webhook_signed

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with (
            patch("services.webhook_delivery.is_private_url", return_value=False),
            patch("services.webhook_delivery.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            code, err = await _deliver_webhook_signed(
                "https://example.com/hook", "secret123", {"test": True}, uuid.uuid4()
            )
        assert code == 200
        assert err is None

    @pytest.mark.asyncio
    async def test_ssrf_rejected(self):
        from services.alert_evaluator import _deliver_webhook_signed

        with patch("services.webhook_delivery.is_private_url", return_value=True):
            code, err = await _deliver_webhook_signed(
                "http://127.0.0.1/hook", "secret123", {"test": True}, uuid.uuid4()
            )
        assert code is None
        assert "SSRF" in err

    @pytest.mark.asyncio
    async def test_empty_secret_still_delivers(self):
        """Legacy rules with empty secret deliver without signing."""
        from services.alert_evaluator import _deliver_webhook_signed

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with (
            patch("services.webhook_delivery.is_private_url", return_value=False),
            patch("services.webhook_delivery.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client
            code, err = await _deliver_webhook_signed("https://example.com/hook", "", {"test": True}, uuid.uuid4())
        assert code == 200
        assert err is None


class TestEvaluateAlerts:
    @pytest.mark.asyncio
    async def test_full_flow_fires_alert_and_records_history(self):
        from services.alert_evaluator import evaluate_alerts

        rule = MagicMock()
        rule.id = uuid.uuid4()
        rule.name = "High Error Rate"
        rule.metric = "error_rate"
        rule.threshold = 0.10
        rule.condition = "above"
        rule.target_type = "agent"
        rule.target_id = "agent-1"
        rule.webhook_url = "https://example.com/webhook"
        rule.webhook_secret = "a" * 64
        rule.status = "active"
        rule.last_triggered = None

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [rule]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "services.alert_evaluator.async_session",
                return_value=mock_session_ctx,
            ),
            patch(
                "services.alert_evaluator._query_metric",
                new_callable=AsyncMock,
                return_value=0.25,
            ),
            patch(
                "services.alert_evaluator._deliver_webhook_signed",
                new_callable=AsyncMock,
                return_value=(200, None),
            ),
        ):
            await evaluate_alerts({})
        mock_db.add.assert_called_once()
        assert rule.last_triggered is not None

    @pytest.mark.asyncio
    async def test_condition_not_met_skips_webhook(self):
        from services.alert_evaluator import evaluate_alerts

        rule = MagicMock()
        rule.id = uuid.uuid4()
        rule.name = "Low Error Rate"
        rule.metric = "error_rate"
        rule.threshold = 0.50
        rule.condition = "above"
        rule.target_type = "all"
        rule.target_id = ""
        rule.webhook_url = "https://example.com/webhook"
        rule.status = "active"
        rule.last_triggered = None

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [rule]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "services.alert_evaluator.async_session",
                return_value=mock_session_ctx,
            ),
            patch(
                "services.alert_evaluator._query_metric",
                new_callable=AsyncMock,
                return_value=0.05,
            ),
            patch(
                "services.alert_evaluator._deliver_webhook_signed",
                new_callable=AsyncMock,
            ) as mock_deliver,
        ):
            await evaluate_alerts({})
        mock_deliver.assert_not_called()
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_metric_none_skips_rule(self):
        from services.alert_evaluator import evaluate_alerts

        rule = MagicMock()
        rule.id = uuid.uuid4()
        rule.metric = "error_rate"
        rule.threshold = 0.10
        rule.condition = "above"
        rule.target_type = "all"
        rule.target_id = ""
        rule.webhook_url = "https://example.com/webhook"
        rule.status = "active"

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [rule]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "services.alert_evaluator.async_session",
                return_value=mock_session_ctx,
            ),
            patch(
                "services.alert_evaluator._query_metric",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            await evaluate_alerts({})
        mock_db.add.assert_not_called()


class TestAlertRouteSSRF:
    def test_validate_webhook_url_rejects_private(self):
        from api.routes.alert import _validate_webhook_url

        with patch("api.routes.alert.is_private_url", return_value=True):
            with pytest.raises(Exception) as exc_info:
                _validate_webhook_url("http://10.0.0.1/hook")
            assert exc_info.value.status_code == 400
            assert "private" in exc_info.value.detail.lower()

    def test_validate_webhook_url_rejects_non_http(self):
        from api.routes.alert import _validate_webhook_url

        with pytest.raises(Exception) as exc_info:
            _validate_webhook_url("ftp://example.com/hook")
        assert exc_info.value.status_code == 400
        assert "http" in exc_info.value.detail.lower()

    def test_validate_webhook_url_allows_empty(self):
        from api.routes.alert import _validate_webhook_url

        _validate_webhook_url("")

    def test_validate_webhook_url_allows_public_https(self):
        from api.routes.alert import _validate_webhook_url

        with patch("api.routes.alert.is_private_url", return_value=False):
            _validate_webhook_url("https://hooks.slack.com/services/T00/B00/xxx")


def _alert_route_user(*, role="admin", org_id=None, user_id=None):
    from models.user import UserRole

    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.role = getattr(UserRole, role)
    user.org_id = org_id
    return user


def _alert_route_rule(*, created_by=None, webhook_url="https://example.com/hook"):
    rule = MagicMock()
    rule.id = uuid.uuid4()
    rule.name = "Latency"
    rule.metric = "latency_p99"
    rule.threshold = 1000.0
    rule.condition = "above"
    rule.target_type = "all"
    rule.target_id = ""
    rule.webhook_url = webhook_url
    rule.webhook_secret = "old-secret-value"
    rule.created_by = created_by or uuid.uuid4()
    rule.status = "active"
    rule.last_triggered = None
    rule.created_at = datetime.now(UTC)
    return rule


def _alert_route_db(rule, creator=None):
    result = MagicMock()
    result.scalar_one_or_none.return_value = creator

    db = AsyncMock()
    db.get = AsyncMock(return_value=rule)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestAlertOrgScopedRoutes:
    @pytest.mark.asyncio
    async def test_missing_alert_update_returns_404(self):
        from api.routes.alert import update_alert
        from schemas.alert import AlertRuleUpdate

        current_user = _alert_route_user(org_id=uuid.uuid4())
        db = _alert_route_db(None)

        with pytest.raises(Exception) as exc_info:
            await update_alert(uuid.uuid4(), AlertRuleUpdate(status="paused"), db, current_user)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_same_org_owner_can_delete_alert(self):
        from api.routes.alert import delete_alert

        org_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        current_user = _alert_route_user(role="user", org_id=org_id, user_id=owner_id)
        creator = _alert_route_user(role="user", org_id=org_id, user_id=owner_id)
        rule = _alert_route_rule(created_by=owner_id)
        db = _alert_route_db(rule, creator)
        db.delete = AsyncMock()

        await delete_alert(rule.id, db, current_user)

        db.delete.assert_awaited_once_with(rule)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_same_org_owner_can_get_alert_history(self):
        from api.routes.alert import get_alert_history

        org_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        current_user = _alert_route_user(role="user", org_id=org_id, user_id=owner_id)
        creator = _alert_route_user(role="user", org_id=org_id, user_id=owner_id)
        rule = _alert_route_rule(created_by=owner_id)

        creator_result = MagicMock()
        creator_result.scalar_one_or_none.return_value = creator
        history_result = MagicMock()
        history_result.scalars.return_value.all.return_value = []

        db = AsyncMock()
        db.get = AsyncMock(return_value=rule)
        db.execute = AsyncMock(side_effect=[creator_result, history_result])

        history = await get_alert_history(rule.id, db=db, current_user=current_user)

        assert history == []
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_same_org_admin_can_rotate_webhook_secret(self):
        from api.routes.alert import rotate_webhook_secret

        org_id = uuid.uuid4()
        creator_id = uuid.uuid4()
        current_user = _alert_route_user(org_id=org_id)
        creator = _alert_route_user(role="user", org_id=org_id, user_id=creator_id)
        rule = _alert_route_rule(created_by=creator_id)
        db = _alert_route_db(rule, creator)

        response = await rotate_webhook_secret(rule.id, db, current_user)

        assert response.webhook_secret_last4 == rule.webhook_secret[-4:]
        assert rule.webhook_secret != "old-secret-value"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cross_org_admin_cannot_rotate_webhook_secret(self):
        from api.routes.alert import rotate_webhook_secret

        current_user = _alert_route_user(org_id=uuid.uuid4())
        creator = _alert_route_user(role="user", org_id=uuid.uuid4())
        rule = _alert_route_rule(created_by=creator.id)
        db = _alert_route_db(rule, creator)

        with pytest.raises(Exception) as exc_info:
            await rotate_webhook_secret(rule.id, db, current_user)

        assert exc_info.value.status_code == 404
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_same_org_admin_can_reveal_webhook_secret(self):
        from api.routes.alert import reveal_webhook_secret

        org_id = uuid.uuid4()
        creator_id = uuid.uuid4()
        current_user = _alert_route_user(org_id=org_id)
        creator = _alert_route_user(role="user", org_id=org_id, user_id=creator_id)
        rule = _alert_route_rule(created_by=creator_id)
        db = _alert_route_db(rule, creator)

        response = await reveal_webhook_secret(rule.id, db, current_user)

        assert response.webhook_secret == rule.webhook_secret

    @pytest.mark.asyncio
    async def test_cross_org_admin_cannot_reveal_webhook_secret(self):
        from api.routes.alert import reveal_webhook_secret

        current_user = _alert_route_user(org_id=uuid.uuid4())
        creator = _alert_route_user(role="user", org_id=uuid.uuid4())
        rule = _alert_route_rule(created_by=creator.id)
        db = _alert_route_db(rule, creator)

        with pytest.raises(Exception) as exc_info:
            await reveal_webhook_secret(rule.id, db, current_user)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_org_admin_cannot_test_webhook(self):
        from api.routes.alert import test_webhook

        current_user = _alert_route_user(org_id=uuid.uuid4())
        creator = _alert_route_user(role="user", org_id=uuid.uuid4())
        rule = _alert_route_rule(created_by=creator.id)
        db = _alert_route_db(rule, creator)

        with pytest.raises(Exception) as exc_info:
            await test_webhook(rule.id, db, current_user)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_local_mode_admin_can_reveal_webhook_secret(self):
        from api.routes.alert import reveal_webhook_secret

        current_user = _alert_route_user(org_id=None)
        rule = _alert_route_rule()
        db = _alert_route_db(rule)

        response = await reveal_webhook_secret(rule.id, db, current_user)

        assert response.webhook_secret == rule.webhook_secret
        db.execute.assert_not_awaited()


class TestAlertHistorySchema:
    def test_schema_from_attributes(self):
        from schemas.alert import AlertHistoryResponse

        data = {
            "id": uuid.uuid4(),
            "alert_rule_id": uuid.uuid4(),
            "metric_value": 0.25,
            "threshold": 0.10,
            "condition": "above",
            "fired_at": datetime.now(UTC),
            "delivery_status": "delivered",
            "response_code": 200,
            "error": None,
            "created_at": datetime.now(UTC),
        }
        resp = AlertHistoryResponse(**data)
        assert resp.metric_value == 0.25
        assert resp.delivery_status == "delivered"
        assert resp.response_code == 200

    def test_schema_nullable_fields(self):
        from schemas.alert import AlertHistoryResponse

        data = {
            "id": uuid.uuid4(),
            "alert_rule_id": uuid.uuid4(),
            "metric_value": 500.0,
            "threshold": 1000.0,
            "condition": "below",
            "fired_at": datetime.now(UTC),
            "delivery_status": "failed",
            "response_code": None,
            "error": "connection refused",
            "created_at": datetime.now(UTC),
        }
        resp = AlertHistoryResponse(**data)
        assert resp.response_code is None
        assert resp.error == "connection refused"


class TestAlertRuleUpdateSchema:
    def test_status_only(self):
        from schemas.alert import AlertRuleUpdate

        update = AlertRuleUpdate(status="paused")
        assert update.status == "paused"
        assert update.webhook_url is None

    def test_webhook_url_only(self):
        from schemas.alert import AlertRuleUpdate

        update = AlertRuleUpdate(webhook_url="https://example.com/hook")
        assert update.status is None
        assert update.webhook_url == "https://example.com/hook"

    def test_both_fields(self):
        from schemas.alert import AlertRuleUpdate

        update = AlertRuleUpdate(status="active", webhook_url="https://example.com/hook")
        assert update.status == "active"
        assert update.webhook_url == "https://example.com/hook"
