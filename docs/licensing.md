<!-- SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Observal Licensing

## Overview

Observal uses a dual-licensing model:

| Component | License | Location |
|-----------|---------|----------|
| Core platform | GNU Affero General Public License v3.0 (AGPL-3.0-only) | Everything outside `ee/` |
| Enterprise features | Observal Enterprise License v1.0 (proprietary) | `ee/` directory |

## Open-Source Core (AGPL-3.0)

The open-source core is fully functional on its own. You can self-host, modify, and distribute it under the terms of the AGPL-3.0. The AGPL requires that:

1. **Source disclosure** — If you modify Observal and make it available over a network (e.g., as a hosted service), you must make your modified source code available to users under the same AGPL terms.
2. **Copyleft** — Derivative works must also be licensed under AGPL-3.0.
3. **No additional restrictions** — You cannot impose further restrictions beyond what the AGPL permits.

This applies to all code outside the `ee/` directory.

## Enterprise Edition (Commercial License)

The `ee/` directory contains proprietary enterprise features (SAML SSO, exec dashboard, compliance audit) that require a commercial license for production use.

### What the commercial license grants

When you purchase an Observal Enterprise license:

1. **No AGPL copyleft obligation** — You may use the combined product (core + enterprise) without the requirement to disclose your modifications or derivative works.
2. **No source disclosure requirement** — You are not required to provide source code to your users, even when offering Observal as a network service.
3. **Production use of enterprise features** — You may deploy `ee/` code in production, staging, and user-facing environments.
4. **Proprietary modifications** — You may make private modifications to the codebase without releasing them.

In short: **purchasing an Enterprise license removes all AGPL obligations** for your organization's use of Observal.

### What the commercial license does NOT grant

- The right to redistribute Observal (core or enterprise) to third parties as a standalone product.
- The right to sublicense.
- The right to use enterprise code in a competing product.

See [`ee/LICENSE`](../ee/LICENSE) for complete terms.

## For contributors

All contributions to the open-source core (outside `ee/`) require signing the [Contributor License Agreement](../CLA.md). The CLA grants BlazeUp AI the right to sublicense contributions — including under the commercial license — while you retain copyright.

Community contributions to the `ee/` directory are not accepted.

## For enterprise buyers

If your legal or procurement team needs clarification:

- **Contact:** contact@observal.io
- **Website:** https://observal.io/

### Common questions

**Q: If I self-host the open-source core without enterprise features, do I need a commercial license?**
A: No. The AGPL governs your use. You only need a commercial license if you want to avoid AGPL obligations or use enterprise features.

**Q: If I modify the core and use it internally (not over a network), do I need to share source?**
A: No. The AGPL's network-use clause (Section 13) only triggers when you make the software available to others over a network.

**Q: Does the commercial license cover all future versions?**
A: License terms (duration, version coverage) are specified in your commercial agreement. Contact sales for details.
