<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: LicenseRef-Observal-Enterprise -->

# Enterprise Edition

Source-available enterprise features. Loaded when `OBSERVAL_LICENSE_KEY` is set and contains a valid signed JWT. Features are individually gated: the JWT's `features` array controls which capabilities activate.

**License:** `ee/LICENSE`. Commercial license required for production. No community contributions accepted here.

**Critical constraint:** Core never imports from `ee/`. One-way dependency only. Open-source edition is fully functional without this directory.

## How it loads

`observal-server/main.py` calls `register_enterprise(app, settings)` from `ee/__init__.py`:

1. Validates license JWT via `ee/license.py` (checks signature, expiry, org_id, features)
2. Mounts EE routes (SAML, SCIM, audit, SSO admin, exec dashboard)
3. Adds `EnterpriseGuardMiddleware` (503 on EE routes if license invalid/expired)

## License key format

Signed JWT containing:

```json
{
  "org_id": "uuid",
  "features": ["saml", "scim", "audit", "exec_dashboard"],
  "exp": 1750000000
}
```

Usage in code: `from ee.license import is_feature_licensed`. Returns bool. Generate keys with `ee/scripts/generate_license.py`.

## Feature inventory

### Audit (compliance-grade)

Loguru-based middleware captures every API request. Events classified by sensitivity level.

- `ee/observal_server/routes/audit.py`: query + export (CSV/JSON, max 10k rows)
- `ee/observal_server/services/audit.py`: sink to ClickHouse `audit_log` table
- `api/middleware/audit.py` (core): the middleware itself
- `services/audit/classification.py` (core): event classification rules
- `observal_cli/audit.py`: CLI-side audit event emission

### SAML 2.0 SSO

Full implementation: login initiation, ACS callback, SP metadata, admin configuration.

- Routes: `sso_saml.py`, `admin_sso.py`
- Service: `services/saml.py`

### SCIM 2.0

User provisioning: list, create, get, update, delete.

- Route: `scim.py`
- Service: `services/scim_service.py`

### Exec dashboard

Executive analytics dashboard. Route: `exec_dashboard.py`.

## Frontend architecture

NO `web/ee/` directory. Enterprise pages live in `web/src/app/(admin)/` and call license-gated endpoints. Server returns 403 for unlicensed features. Frontend shows upgrade prompts.

## Directory layout

```
ee/
├── __init__.py                    # register_enterprise() entrypoint
├── LICENSE
├── license.py                     # is_feature_licensed(), require_license(), get_license_info()
├── AGENTS.md
├── README.md
├── docs/cli.md
├── scripts/generate_license.py
├── observal_server/
│   ├── middleware/enterprise_guard.py
│   ├── routes/ (audit, admin_sso, exec_dashboard, scim, sso_saml)
│   └── services/ (audit, config_validator, saml, scim_service)
└── plugins/__init__.py            # Future integrations placeholder
```

## Coding patterns for EE code

- Import core freely: `from services.clickhouse.query import query`, `from models.user import User`
- Never expose EE imports to core: if core needs to call EE functionality, use a stub pattern (core defines the interface, EE provides the implementation, loaded at runtime)
- Gate routes with `require_license("feature_name")` dependency
- All EE tests live in `ee/` or use `pytest.importorskip("ee")`
- The `EnterpriseGuardMiddleware` is the last line of defense: even if a route is mounted, requests fail with 503 if the license is invalid
