# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

from importlib import import_module

from fastapi import FastAPI
from loguru import logger as optic
from strawberry.fastapi import GraphQLRouter

from api.graphql import get_context_dep, schema
from api.routes.admin import router as admin_router
from api.routes.agent import router as agent_router
from api.routes.alert import router as alert_router
from api.routes.audit import router as audit_router
from api.routes.auth import router as auth_router
from api.routes.bulk import router as bulk_router
from api.routes.co_authors import router as co_authors_router
from api.routes.component_source import router as component_source_router
from api.routes.config import router as config_router
from api.routes.dashboard import router as dashboard_router
from api.routes.device_auth import router as device_auth_router
from api.routes.feedback import router as feedback_router
from api.routes.hook import router as hook_router
from api.routes.ingest import router as ingest_router
from api.routes.insights import router as insights_router
from api.routes.jwks import router as jwks_router
from api.routes.layer_snapshot import router as layer_snapshot_router
from api.routes.logs_stream import router as logs_stream_router
from api.routes.mcp import router as mcp_router
from api.routes.preview import router as preview_router
from api.routes.prompt import router as prompt_router
from api.routes.review import router as review_router
from api.routes.sandbox import router as sandbox_router
from api.routes.sessions import router as sessions_router
from api.routes.skill import router as skill_router
from api.routes.support import router as support_router
from api.routes.telemetry import router as telemetry_router
from api.routes.users import router as users_router
from config import HAS_LICENSE, settings

REST_ROUTERS = (
    auth_router,
    device_auth_router,
    jwks_router,
    mcp_router,
    review_router,
    agent_router,
    preview_router,
    skill_router,
    hook_router,
    prompt_router,
    sandbox_router,
    telemetry_router,
    dashboard_router,
    feedback_router,
    insights_router,
    ingest_router,
    admin_router,
    alert_router,
    sessions_router,
    component_source_router,
    bulk_router,
    co_authors_router,
    config_router,
    support_router,
    layer_snapshot_router,
    logs_stream_router,
    audit_router,
    users_router,
)


def mount_enterprise_routes(app: FastAPI) -> None:
    if not HAS_LICENSE:
        return

    try:
        enterprise_module = import_module("ee")
        enterprise_routes_module = import_module("ee.observal_server.routes")
        register_enterprise_middleware = enterprise_module.register_enterprise_middleware
        mount_ee_routes = enterprise_routes_module.mount_ee_routes
        register_enterprise_middleware(app, settings)
        mount_ee_routes(app)
    except (ImportError, RuntimeError, AttributeError) as ee_err:
        optic.warning("enterprise features unavailable: {}", str(ee_err))
        app.state.enterprise_issues = [str(ee_err)]


def include_graphql_routes(app: FastAPI) -> None:
    graphql_app = GraphQLRouter(schema, context_getter=get_context_dep)
    app.include_router(graphql_app, prefix="/api/v1/graphql")


def include_rest_routes(app: FastAPI) -> None:
    for router in REST_ROUTERS:
        app.include_router(router)


def configure_routes(app: FastAPI) -> None:
    mount_enterprise_routes(app)
    include_graphql_routes(app)
    include_rest_routes(app)
