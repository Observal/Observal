#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

set -euo pipefail

# Observal Server Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install-server.sh | bash
#
# Options (via env vars):
#   OBSERVAL_VERSION=latest        Version to install (default: latest)
#   OBSERVAL_INSTALL_DIR=/path     Install directory (default: /opt/observal)
#   OBSERVAL_FORCE=1               Skip overwrite confirmation on re-install

GITHUB_REPO="BlazeUp-AI/Observal"
VERSION="${OBSERVAL_VERSION:-latest}"
INSTALL_DIR="${OBSERVAL_INSTALL_DIR:-/opt/observal}"
BASE_URL="${OBSERVAL_BASE_URL:-}"  # Override for testing (e.g. http://localhost:9999)

# ── Helpers ──────────────────────────────────────────────────

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33mWARN:\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }
die()   { error "$@"; exit 1; }

# ── Pre-flight ───────────────────────────────────────────────

command -v curl >/dev/null 2>&1 || die "'curl' is required but not found."
command -v docker >/dev/null 2>&1 || die "Docker is required. Install: https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."

# ── Resolve version ──────────────────────────────────────────

if [ "$VERSION" = "latest" ]; then
  VERSION=$(curl -fsSL "https://api.github.com/repos/$GITHUB_REPO/releases/latest" \
    | grep '"tag_name"' | head -1 | cut -d'"' -f4)
  [ -n "$VERSION" ] || die "Could not determine latest version"
fi

info "Installing Observal Server $VERSION"

# ── Download ─────────────────────────────────────────────────

ARTIFACT="observal-server-${VERSION}.tar.gz"
if [ -n "$BASE_URL" ]; then
  URL="${BASE_URL}/${ARTIFACT}"
else
  URL="https://github.com/$GITHUB_REPO/releases/download/$VERSION/$ARTIFACT"
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

info "Downloading server package..."
curl -fsSL -o "$TMPDIR/$ARTIFACT" "$URL" || die "Download failed. Check that $VERSION exists at https://github.com/$GITHUB_REPO/releases"

# ── Unpack ───────────────────────────────────────────────────

if [ -d "$INSTALL_DIR" ] && [ "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
  if [ "${OBSERVAL_FORCE:-}" = "1" ]; then
    info "Overwriting existing installation at $INSTALL_DIR"
  else
    warn "Directory $INSTALL_DIR already exists and is not empty."
    printf 'Overwrite? [y/N]: '
    read -r confirm </dev/tty
    [ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || die "Aborted."
  fi
fi

info "Unpacking to $INSTALL_DIR..."
if [ -w "$(dirname "$INSTALL_DIR")" ]; then
  mkdir -p "$INSTALL_DIR"
  tar -xzf "$TMPDIR/$ARTIFACT" -C "$INSTALL_DIR" --strip-components=1
else
  sudo mkdir -p "$INSTALL_DIR"
  sudo tar -xzf "$TMPDIR/$ARTIFACT" -C "$INSTALL_DIR" --strip-components=1
  sudo chown -R "$(id -u):$(id -g)" "$INSTALL_DIR"
fi

# ── Run setup ────────────────────────────────────────────────

info "Running guided setup..."
OBSERVAL_INSTALL_DIR="$INSTALL_DIR" bash "$INSTALL_DIR/setup.sh" </dev/tty
