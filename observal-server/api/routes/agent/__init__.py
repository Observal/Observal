# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Agent routes package. Sub-modules register routes on the shared router."""

# Import sub-modules so they register their routes on the shared router.
from . import crud, draft, install  # noqa: F401
from ._router import router  # noqa: F401
from .install import install_agent  # noqa: F401
