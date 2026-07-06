# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Domain exceptions for migration operations."""

from __future__ import annotations


class MigrationError(Exception):
    """Base exception for all migration errors."""


class ChecksumMismatchError(MigrationError):
    """Raised when artifact checksums do not match the manifest."""


class PrerequisiteError(MigrationError):
    """Raised when a prerequisite is not met (e.g. PG manifest gate for CH export)."""


class ConnectionFailedError(MigrationError):
    """Raised when a database connection cannot be established."""


class ArtifactValidationError(MigrationError):
    """Raised when an uploaded artifact fails type/size/format validation."""
