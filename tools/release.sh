#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

set -euo pipefail

# Usage: tools/release.sh <major|feature|patch>
#
#   major   -- bump X in X.Y.Z (approval gate in CI)
#   feature -- bump Y in X.Y.Z (approval gate in CI)
#   patch   -- bump Z in X.Y.Z (no approval gate)
#
# Creates a release branch, bumps versions, generates changelog,
# and opens a PR against upstream/main. Merging the PR triggers
# the release workflow automatically.

BUMP_TYPE="${1:-}"
PYPROJECT="pyproject.toml"
CLIFF_CONFIG="cliff.toml"
UPSTREAM_REMOTE="${OBSERVAL_UPSTREAM:-upstream}"
FORK_REMOTE="${OBSERVAL_FORK:-origin}"

# ── Helpers ──────────────────────────────────────────────────

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

get_version() {
  python3 -c "
import re, pathlib
m = re.search(r'^version\s*=\s*\"([^\"]+)\"', pathlib.Path('$PYPROJECT').read_text(), re.M)
print(m.group(1))
"
}

set_version_in_file() {
  local file="$1" version="$2"
  python3 -c "
import re, pathlib
p = pathlib.Path('$file')
text = p.read_text()
text = re.sub(r'^(version\s*=\s*\")([^\"]+)(\")', r'\g<1>$version\3', text, count=1, flags=re.M)
p.write_text(text)
"
}

run_git_cliff() {
  if command -v git-cliff >/dev/null 2>&1; then
    git-cliff "$@"
  else
    uvx git-cliff "$@"
  fi
}

# ── Validate input ───────────────────────────────────────────

case "$BUMP_TYPE" in
  major|feature|patch) ;;
  *)
    echo "Usage: tools/release.sh <major|feature|patch>"
    echo ""
    echo "  major   -- bump X in X.Y.Z  (e.g., 0.1.0 -> 1.0.0)"
    echo "  feature -- bump Y in X.Y.Z  (e.g., 0.1.0 -> 0.2.0)"
    echo "  patch   -- bump Z in X.Y.Z  (e.g., 0.1.0 -> 0.1.1)"
    exit 1
    ;;
esac

# ── Pre-flight checks ───────────────────────────────────────

command -v git-cliff >/dev/null 2>&1 || command -v uvx >/dev/null 2>&1 || die "git-cliff or uvx required"
command -v gh >/dev/null 2>&1 || die "GitHub CLI (gh) is required"
[ -f "$PYPROJECT" ] || die "Run from repo root (pyproject.toml not found)"
[ -z "$(git status --porcelain)" ] || die "Working tree is dirty. Commit or stash changes first."

# Must be on main
BRANCH=$(git rev-parse --abbrev-ref HEAD)
[ "$BRANCH" = "main" ] || die "Releases must be cut from main (currently on $BRANCH)"

# Ensure main is up to date with upstream
info "Syncing with $UPSTREAM_REMOTE/main..."
git fetch "$UPSTREAM_REMOTE" main
LOCAL_SHA=$(git rev-parse HEAD)
UPSTREAM_SHA=$(git rev-parse "$UPSTREAM_REMOTE/main")
[ "$LOCAL_SHA" = "$UPSTREAM_SHA" ] || die "Local main is not up to date with $UPSTREAM_REMOTE/main. Run: git pull $UPSTREAM_REMOTE main"

CURRENT_VERSION=$(get_version)
info "Current version: $CURRENT_VERSION"

# ── Compute new version ─────────────────────────────────────

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

case "$BUMP_TYPE" in
  major)
    NEW_VERSION="$((MAJOR + 1)).0.0"
    ;;
  feature)
    NEW_VERSION="${MAJOR}.$((MINOR + 1)).0"
    ;;
  patch)
    NEW_VERSION="${MAJOR}.${MINOR}.$((PATCH + 1))"
    ;;
esac

info "$BUMP_TYPE release: $CURRENT_VERSION -> $NEW_VERSION"

# ── Create release branch ───────────────────────────────────

RELEASE_BRANCH="release/v$NEW_VERSION"
git checkout -b "$RELEASE_BRANCH"

# ── Bump versions ────────────────────────────────────────────

set_version_in_file "$PYPROJECT" "$NEW_VERSION"
set_version_in_file "observal-server/pyproject.toml" "$NEW_VERSION"

# Bump web/package.json
info "Bumping web/package.json..."
python3 -c "
import json, pathlib
pkg = pathlib.Path('web/package.json')
data = json.loads(pkg.read_text())
data['version'] = '$NEW_VERSION'
pkg.write_text(json.dumps(data, indent=2) + '\n')
"

# Bump packages/pi-extension/package.json
if [ -f packages/pi-extension/package.json ]; then
  info "Bumping packages/pi-extension/package.json..."
  python3 -c "
import json, pathlib
pkg = pathlib.Path('packages/pi-extension/package.json')
data = json.loads(pkg.read_text())
data['version'] = '$NEW_VERSION'
pkg.write_text(json.dumps(data, indent=2) + '\n')
"
fi

# ── Update uv.lock ──────────────────────────────────────────

info "Updating root uv.lock..."
uv lock

info "Updating observal-server/uv.lock..."
(cd observal-server && uv lock)

# ── Generate changelog ───────────────────────────────────────

info "Generating changelog..."
run_git_cliff --config "$CLIFF_CONFIG" --tag "v$NEW_VERSION" --output CHANGELOG.md

# ── Commit and push branch ──────────────────────────────────

git add "$PYPROJECT" observal-server/pyproject.toml web/package.json packages/pi-extension/package.json uv.lock observal-server/uv.lock CHANGELOG.md
git commit -s -m "bump(release): v$NEW_VERSION"

info "Pushing release branch to $FORK_REMOTE..."
git push "$FORK_REMOTE" "$RELEASE_BRANCH"

# ── Open pull request ────────────────────────────────────────

UPSTREAM_REPO=$(git remote get-url "$UPSTREAM_REMOTE" | sed -E 's#.+github\.com[:/](.+)\.git$#\1#; s#.+github\.com[:/](.+)$#\1#')
FORK_OWNER=$(git remote get-url "$FORK_REMOTE" | sed -E 's#.+github\.com[:/]([^/]+)/.+#\1#')

info "Opening PR against $UPSTREAM_REPO..."

PR_BODY="## Release v$NEW_VERSION ($BUMP_TYPE)

Bumps version \`$CURRENT_VERSION\` → \`$NEW_VERSION\` and regenerates changelog.

**Merging this PR will automatically trigger the release pipeline.**

### What happens after merge
- CLI binaries built for 6 platforms (Linux/macOS/Windows, x64/arm64)
- Docker images pushed to GHCR
- Server deployment tarball packaged
- PyPI package published
- **Approval required** in the \`production\` environment before GitHub Release publishes"

PR_URL=$(gh pr create \
  --repo "$UPSTREAM_REPO" \
  --head "$FORK_OWNER:$RELEASE_BRANCH" \
  --base main \
  --title "bump(release): v$NEW_VERSION" \
  --body "$PR_BODY")

info ""
info "Release PR created: $PR_URL"
info ""
info "Next steps:"
info "  1. Review and merge the PR"
info "  2. GitHub Actions will build all artifacts"
info "  3. Approve the release in the 'production' environment"

# Return to main
git checkout main
