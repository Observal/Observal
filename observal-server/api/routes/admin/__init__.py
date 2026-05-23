# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Admin routes package. Sub-modules register routes on the shared router."""

# Import sub-modules so they register their routes on the shared router.
from . import enterprise_settings, org, retention, users  # noqa: F401
from ._router import router  # noqa: F401
