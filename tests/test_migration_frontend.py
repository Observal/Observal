# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Stub test file for frontend component tests (10.4).

Frontend component tests for the Migration_Panel require React Testing Library
and vitest, and are run separately via the web/ package test infrastructure:

    cd web && pnpm test

Components to test:
- MigrateButton renders only for super_admin and is distinct from ExportDropdown
- ExportDropdown is preserved and unchanged
- Dialog tabs (Export / Import / Validate)
- Active job state transitions: form → progress → result
- Export form shows only postgres/both, disabled clickhouse with tooltip
- Import form pre-fills org/project from server

Requirements: 1.1, 1.2, 1.3, 1.4, 3.9, 4.8, 6.3, 6.6, 7.7
"""


class TestFrontendComponentStub:
    """Placeholder: frontend tests run in the web/ vitest environment."""

    def test_stub_note(self):
        """This file is a placeholder. React component tests run via vitest."""
        # Frontend tests for the Migration Panel are located in:
        #   web/src/components/admin/__tests__/MigrationPanel.test.tsx
        # Run with: cd web && pnpm test
        pass
