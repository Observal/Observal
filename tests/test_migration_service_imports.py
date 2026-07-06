# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Checkpoint: verify observal_shared.migration imports cleanly without FastAPI/typer/rich.

Requirement 8.1: The shared Migration_Service must be importable and callable
by both the REST API and CLI without framework coupling.
"""

from __future__ import annotations

import importlib
import sys

# Modules to block. The shared service must not depend on these.
BLOCKED_MODULES = ("fastapi", "typer", "rich")

# All submodules of the migration service package.
MIGRATION_SUBMODULES = (
    "observal_shared.migration",
    "observal_shared.migration.archive",
    "observal_shared.migration.ch_export",
    "observal_shared.migration.ch_import",
    "observal_shared.migration.connections",
    "observal_shared.migration.constants",
    "observal_shared.migration.encoding",
    "observal_shared.migration.exceptions",
    "observal_shared.migration.pg_export",
    "observal_shared.migration.pg_import",
    "observal_shared.migration.progress",
    "observal_shared.migration.results",
    "observal_shared.migration.validation",
)


class _BlockedImportError(ImportError):
    """Raised when a blocked module is imported during the test."""


def _make_blocking_finder(blocked: tuple[str, ...]):
    """Create a sys.meta_path finder that raises ImportError for blocked modules."""

    class _BlockingFinder:
        def find_module(self, fullname, path=None):
            for prefix in blocked:
                if fullname == prefix or fullname.startswith(prefix + "."):
                    return self
            return None

        def load_module(self, fullname):
            raise _BlockedImportError(f"Import of '{fullname}' is blocked during this test")

    return _BlockingFinder()


def _purge_modules(prefixes: tuple[str, ...]) -> dict[str, object]:
    """Remove modules matching any prefix from sys.modules, return removed."""
    removed = {}
    for key in list(sys.modules):
        for prefix in prefixes:
            if key == prefix or key.startswith(prefix + "."):
                removed[key] = sys.modules.pop(key)
                break
    return removed


class TestMigrationServiceImportsCleanly:
    """Verify the migration package imports without framework dependencies."""

    def test_import_without_fastapi_typer_rich(self):
        """Import observal_shared.migration with fastapi/typer/rich blocked from sys.modules."""
        # 1. Remove any pre-loaded framework modules AND migration modules
        all_prefixes = (*BLOCKED_MODULES, "observal_shared.migration")
        saved = _purge_modules(all_prefixes)

        # 2. Install a blocking finder so they cannot be re-imported
        blocker = _make_blocking_finder(BLOCKED_MODULES)
        sys.meta_path.insert(0, blocker)

        try:
            # 3. Import the migration service fresh
            import observal_shared.migration as mig

            # Force a full reload in case it was cached
            importlib.reload(mig)

            # 4. Verify public entry points are accessible
            assert callable(mig.export_pg)
            assert callable(mig.export_ch)
            assert callable(mig.import_pg)
            assert callable(mig.import_ch)
            assert callable(mig.validate_pg)
            assert callable(mig.validate_ch)

            # 5. Verify exception classes are accessible
            assert issubclass(mig.MigrationError, Exception)
            assert issubclass(mig.ChecksumMismatchError, mig.MigrationError)
            assert issubclass(mig.PrerequisiteError, mig.MigrationError)
            assert issubclass(mig.ConnectionFailedError, mig.MigrationError)
            assert issubclass(mig.ArtifactValidationError, mig.MigrationError)

            # 6. Verify connection param dataclasses
            assert mig.PgConnParams is not None
            assert mig.ChConnParams is not None

            # 7. Verify progress protocol and null reporter
            assert mig.ProgressReporter is not None
            assert mig.NullReporter is not None

            # 8. Verify result dataclasses
            assert mig.ExportResult is not None
            assert mig.ImportResult is not None
            assert mig.ValidationResult is not None
            assert mig.ChecksumResult is not None

            # 9. Confirm blocked modules are NOT in sys.modules
            for mod_name in BLOCKED_MODULES:
                assert mod_name not in sys.modules, f"'{mod_name}' was imported by observal_shared.migration"

        finally:
            # Cleanup: remove blocker and restore saved modules
            sys.meta_path.remove(blocker)
            sys.modules.update(saved)

    def test_no_typer_rich_in_migration_submodules(self):
        """Verify no submodule pulls in typer or rich."""
        # Purge migration modules so we get fresh imports
        saved = _purge_modules((*BLOCKED_MODULES, "observal_shared.migration"))

        blocker = _make_blocking_finder(("typer", "rich"))
        sys.meta_path.insert(0, blocker)

        try:
            for mod_name in MIGRATION_SUBMODULES:
                # Remove if cached, then reimport
                sys.modules.pop(mod_name, None)
                importlib.import_module(mod_name)

            # After all imports, confirm typer/rich are still absent
            assert "typer" not in sys.modules
            assert "rich" not in sys.modules

        finally:
            sys.meta_path.remove(blocker)
            sys.modules.update(saved)
