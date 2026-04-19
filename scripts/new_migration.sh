#!/usr/bin/env bash
#
# Create a new alembic migration with the correct next revision ID.
#
# Usage:
#   ./scripts/new_migration.sh "add foo column to bar table"
#
# Reads the current head from the versions directory, increments it,
# and writes a skeleton migration file.

set -euo pipefail

VERSIONS_DIR="$(cd "$(dirname "$0")/../observal-server/alembic/versions" && pwd)"

if [ $# -lt 1 ]; then
    echo "Usage: $0 \"description of the migration\""
    echo "  e.g. $0 \"add foo column to bar table\""
    exit 1
fi

DESCRIPTION="$1"

# Find the current head revision (highest numeric prefix)
CURRENT_HEAD=$(
    grep -rh '^revision' "$VERSIONS_DIR"/*.py 2>/dev/null \
    | sed 's/revision *= *["'"'"']\(.*\)["'"'"'].*/\1/' \
    | sort -V \
    | tail -1
)

if [ -z "$CURRENT_HEAD" ]; then
    echo "ERROR: Could not determine current head revision from $VERSIONS_DIR"
    exit 1
fi

# Increment: strip leading zeros, add 1, re-pad to 4 digits
NEXT_NUM=$(printf "%04d" $(( 10#$CURRENT_HEAD + 1 )))

# Slugify description for filename
SLUG=$(echo "$DESCRIPTION" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g' | sed 's/__*/_/g' | sed 's/^_//;s/_$//')
FILENAME="${NEXT_NUM}_${SLUG}.py"
FILEPATH="$VERSIONS_DIR/$FILENAME"

TODAY=$(date +%Y-%m-%d)

cat > "$FILEPATH" << PYEOF
"""${DESCRIPTION}.

Revision ID: ${NEXT_NUM}
Revises: ${CURRENT_HEAD}
Create Date: ${TODAY}
"""

from alembic import op

revision = "${NEXT_NUM}"
down_revision = "${CURRENT_HEAD}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass  # TODO: implement


def downgrade() -> None:
    pass  # TODO: implement
PYEOF

echo "Created: $FILEPATH"
echo "  revision = \"$NEXT_NUM\""
echo "  down_revision = \"$CURRENT_HEAD\""
echo ""
echo "Edit the upgrade() and downgrade() functions, then run:"
echo "  make check-migrations"
