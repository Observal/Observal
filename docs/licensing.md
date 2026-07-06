<!-- SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Observal Licensing

## Overview

Observal uses an open-core licensing model:

| Component | License | Location |
|-----------|---------|----------|
| Core platform | Apache License 2.0 (`Apache-2.0`) | Everything outside `ee/` |
| Enterprise features | Observal Enterprise License v1.0, proprietary | `ee/` directory |

## Open-source core

The open-source core is fully functional on its own. You can use, self-host, modify, distribute, and build commercial products with it under the terms of the Apache License 2.0.

Apache-2.0 also includes an explicit patent grant from contributors, subject to the terms in [LICENSE](../LICENSE).

This applies to all code outside the `ee/` directory.

## Enterprise Edition

The `ee/` directory contains proprietary enterprise features, such as SAML SSO, exec dashboard, and compliance audit, that require a commercial license for production use.

### What the commercial license grants

When you purchase an Observal Enterprise license:

1. **Production use of enterprise features:** You may deploy `ee/` code in production, staging, and user-facing environments.
2. **Private enterprise modifications:** You may modify enterprise code for your licensed use, subject to your commercial agreement.
3. **Enterprise support and terms:** Version coverage, duration, support, and deployment rights are specified in your commercial agreement.

### What the commercial license does not grant

- The right to redistribute Observal Enterprise as a standalone product.
- The right to sublicense enterprise code.
- The right to use enterprise code in a competing product.

See [`ee/LICENSE`](../ee/LICENSE) for complete terms.

## For contributors

All contributions to the open-source core outside `ee/` require signing the [Contributor License Agreement](../CLA.md). The CLA grants Observal the right to sublicense contributions, including under a commercial license, while you retain copyright.

Community contributions to the `ee/` directory are not accepted.

## For enterprise buyers

If your legal or procurement team needs clarification:

- **Contact:** contact@observal.io
- **Website:** https://observal.io/

### Common questions

**Q: If I self-host the open-source core without enterprise features, do I need a commercial license?**
A: No. The Apache-2.0 core can be self-hosted without a commercial license. You only need a commercial license to use enterprise features.

**Q: If I modify the core, do I need to share source?**
A: No. Apache-2.0 does not require you to publish your modifications.

**Q: Does the commercial license cover all future versions?**
A: License terms, duration, and version coverage are specified in your commercial agreement. Contact sales for details.
