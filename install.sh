#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

set -euo pipefail

# Observal CLI Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/BlazeUp-AI/Observal/main/install.sh | bash
#
# Options (via env vars):
#   OBSERVAL_VERSION=latest    Version to install (default: latest)
#   OBSERVAL_BIN_DIR=/path     Install directory (default: /usr/local/bin)

GITHUB_REPO="BlazeUp-AI/Observal"
VERSION="${OBSERVAL_VERSION:-latest}"
BIN_DIR="${OBSERVAL_BIN_DIR:-/usr/local/bin}"

# ── Helpers ──────────────────────────────────────────────────

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33mWARN:\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }
die()   { error "$@"; exit 1; }

# ── Detect platform ──────────────────────────────────────────

detect_os() {
  case "$(uname -s)" in
    Linux*)  echo "linux" ;;
    Darwin*) echo "macos" ;;
    MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
    *) die "Unsupported OS: $(uname -s)" ;;
  esac
}

detect_arch() {
  case "$(uname -m)" in
    x86_64|amd64)  echo "x64" ;;
    aarch64|arm64) echo "arm64" ;;
    *) die "Unsupported architecture: $(uname -m)" ;;
  esac
}

OS=$(detect_os)
ARCH=$(detect_arch)

# ── Resolve version ──────────────────────────────────────────

command -v curl >/dev/null 2>&1 || die "'curl' is required but not found."

if [ "$VERSION" = "latest" ]; then
  VERSION=$(curl -fsSL "https://api.github.com/repos/$GITHUB_REPO/releases/latest" \
    | grep '"tag_name"' | head -1 | cut -d'"' -f4)
  [ -n "$VERSION" ] || die "Could not determine latest version"
fi

info "Installing Observal CLI $VERSION ($OS/$ARCH)"

# ── Download and verify ──────────────────────────────────────

EXT=""
[ "$OS" = "windows" ] && EXT=".exe"

ARTIFACT="observal-${OS}-${ARCH}${EXT}"
URL="https://github.com/$GITHUB_REPO/releases/download/$VERSION/$ARTIFACT"
CHECKSUM_URL="https://github.com/$GITHUB_REPO/releases/download/$VERSION/checksums.txt"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

info "Downloading $ARTIFACT..."
curl -fsSL -o "$TMPDIR/$ARTIFACT" "$URL" || die "Download failed. Check that $VERSION exists at https://github.com/$GITHUB_REPO/releases"

info "Verifying checksum..."
curl -fsSL -o "$TMPDIR/checksums.txt" "$CHECKSUM_URL" || warn "Could not download checksums -- skipping verification"
if [ -f "$TMPDIR/checksums.txt" ]; then
  EXPECTED=$(grep "$ARTIFACT" "$TMPDIR/checksums.txt" | awk '{print $1}')
  if [ -n "$EXPECTED" ]; then
    if command -v sha256sum >/dev/null 2>&1; then
      ACTUAL=$(sha256sum "$TMPDIR/$ARTIFACT" | awk '{print $1}')
    else
      ACTUAL=$(shasum -a 256 "$TMPDIR/$ARTIFACT" | awk '{print $1}')
    fi
    [ "$ACTUAL" = "$EXPECTED" ] || die "Checksum mismatch! Expected: $EXPECTED Got: $ACTUAL"
    info "Checksum verified"
  fi
fi

# ── Install ──────────────────────────────────────────────────

INSTALL_PATH="${BIN_DIR}/observal${EXT}"
if [ -w "$BIN_DIR" ]; then
  mv "$TMPDIR/$ARTIFACT" "$INSTALL_PATH"
  chmod +x "$INSTALL_PATH"
else
  info "Installing to $BIN_DIR requires sudo"
  sudo mv "$TMPDIR/$ARTIFACT" "$INSTALL_PATH"
  sudo chmod +x "$INSTALL_PATH"
fi

info "Installed observal to $INSTALL_PATH"
info "Run 'observal --version' to verify."
