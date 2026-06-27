#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

set -euo pipefail

# Observal Server Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/Observal/Observal/main/install-server.sh | bash -s -- [OPTIONS]
#
# Options:
#   --license-key KEY          Enterprise license key (enables enterprise edition)
#   --version VERSION          Version to install (default: latest)
#   --install-dir DIR          Install directory (default: ~/.observal on macOS, /opt/observal on Linux)
#   --force                    Skip overwrite confirmation on re-install
#
# Environment variable overrides (lower priority than flags):
#   OBSERVAL_LICENSE_KEY       Enterprise license key
#   OBSERVAL_VERSION=latest    Version to install
#   OBSERVAL_INSTALL_DIR       Install directory
#   OBSERVAL_FORCE=1           Skip overwrite confirmation

GITHUB_REPO="Observal/Observal"

# Ed25519 public key for license verification (base64-encoded, 32 bytes raw)
LICENSE_PUBLIC_KEY="X5Ia46wxT2AxZ6nFlvFnT7ZE6vXoVI208Io3TDoX6N8="

# ── Helpers ──────────────────────────────────────────────────

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }
die() {
    error "$@"
    exit 1
}

# ── Parse arguments ──────────────────────────────────────────

LICENSE_KEY="${OBSERVAL_LICENSE_KEY:-}"
VERSION="${OBSERVAL_VERSION:-latest}"
FORCE="${OBSERVAL_FORCE:-0}"
BASE_URL="${OBSERVAL_BASE_URL:-}"

# Default install directory
if [ -z "${OBSERVAL_INSTALL_DIR:-}" ]; then
    case "$(uname -s)" in
    Darwin) INSTALL_DIR="$HOME/.observal" ;;
    *) INSTALL_DIR="/opt/observal" ;;
    esac
else
    INSTALL_DIR="$OBSERVAL_INSTALL_DIR"
fi

while [ $# -gt 0 ]; do
    case "$1" in
    --license-key)
        [ -n "${2:-}" ] || die "--license-key requires a value"
        LICENSE_KEY="$2"
        shift 2
        ;;
    --license-key=*)
        LICENSE_KEY="${1#--license-key=}"
        shift
        ;;
    --version)
        [ -n "${2:-}" ] || die "--version requires a value"
        VERSION="$2"
        shift 2
        ;;
    --version=*)
        VERSION="${1#--version=}"
        shift
        ;;
    --install-dir)
        [ -n "${2:-}" ] || die "--install-dir requires a value"
        INSTALL_DIR="$2"
        shift 2
        ;;
    --install-dir=*)
        INSTALL_DIR="${1#--install-dir=}"
        shift
        ;;
    --force)
        FORCE=1
        shift
        ;;
    -h | --help)
        cat <<'HELP'
Observal Server Installer
Usage: curl -fsSL https://raw.githubusercontent.com/Observal/Observal/main/install-server.sh | bash -s -- [OPTIONS]

Options:
  --license-key KEY    Enterprise license key (enables enterprise edition)
  --version VERSION    Version to install (default: latest)
  --install-dir DIR    Install directory (default: ~/.observal on macOS, /opt/observal on Linux)
  --force              Skip overwrite confirmation on re-install

Environment variable overrides (lower priority than flags):
  OBSERVAL_LICENSE_KEY   Enterprise license key
  OBSERVAL_VERSION       Version to install
  OBSERVAL_INSTALL_DIR   Install directory
  OBSERVAL_FORCE=1       Skip overwrite confirmation
HELP
        exit 0
        ;;
    *)
        die "Unknown option: $1"
        ;;
    esac
done

# ── License validation ───────────────────────────────────────

EDITION="community"

# NOTE: This function is identical in install.sh, install-server.sh, and
# docker/server-package/setup.sh. If you change the validation logic,
# update all three files together.
validate_license() {
    local key="$1"

    # License format: base64url(json_payload).base64url(ed25519_signature)
    local payload_b64 sig_b64
    payload_b64="${key%%.*}"
    sig_b64="${key#*.}"

    if [ -z "$payload_b64" ] || [ -z "$sig_b64" ] || [ "$payload_b64" = "$sig_b64" ]; then
        return 1
    fi

    python3 - "$payload_b64" "$sig_b64" "$LICENSE_PUBLIC_KEY" 2>/dev/null <<'PYTHON'
import base64, json, sys, time

payload_b64, sig_b64, pub_key_b64 = sys.argv[1], sys.argv[2], sys.argv[3]

# Structural validation (no dependencies needed)
try:
    padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
except Exception:
    sys.exit(1)

if "org_id" not in payload:
    sys.exit(1)

exp = payload.get("exp", 0)
if exp > 0 and time.time() > exp:
    print("EXPIRED", file=sys.stderr)
    sys.exit(2)

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pub_key_bytes = base64.urlsafe_b64decode(pub_key_b64 + "==")
    pub_key = Ed25519PublicKey.from_public_bytes(pub_key_bytes)
    sig_bytes = base64.urlsafe_b64decode(sig_b64 + "==")
    pub_key.verify(sig_bytes, payload_b64.encode())

    print(payload.get("org_id", "unknown"))
    sys.exit(0)
except ImportError:
    print(payload.get("org_id", "unknown"))
    sys.exit(3)
except Exception as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
PYTHON
}

if [ -n "$LICENSE_KEY" ]; then
    info "Validating license key..."
    ORG_ID=""
    if ORG_ID=$(validate_license "$LICENSE_KEY"); then
        EDITION="enterprise"
        info "Valid enterprise license (org: $ORG_ID)"
    else
        EXIT_CODE=$?
        if [ "$EXIT_CODE" -eq 2 ]; then
            die "License key has expired. Contact sales@observal.dev to renew."
        elif [ "$EXIT_CODE" -eq 3 ]; then
            warn "Cannot verify license locally (python3 cryptography package not found)."
            warn "Proceeding with enterprise install — the server will validate at startup."
            EDITION="enterprise"
        else
            die "Invalid license key. Check your key or contact support@observal.dev"
        fi
    fi
else
    info "No license key provided — installing community edition"
fi

# ── Pre-flight ───────────────────────────────────────────────

command -v curl >/dev/null 2>&1 || die "'curl' is required but not found."
command -v docker >/dev/null 2>&1 || die "Docker is required. Install: https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."

# ── Resolve version ──────────────────────────────────────────

if [ "$VERSION" = "latest" ]; then
    VERSION=$(curl -fsSL "https://api.github.com/repos/$GITHUB_REPO/releases/latest" |
        grep '"tag_name"' | head -1 | cut -d'"' -f4)
    [ -n "$VERSION" ] || die "Could not determine latest version"
fi

info "Installing Observal Server $VERSION [$EDITION edition]"

# ── Download ─────────────────────────────────────────────────

# Same server package for both editions; enterprise features activate via the
# license key passed to setup.sh at the end of this script.
ARTIFACT="observal-server-${VERSION}.tar.gz"

if [ -n "$BASE_URL" ]; then
    URL="${BASE_URL}/${ARTIFACT}"
else
    URL="https://github.com/$GITHUB_REPO/releases/download/$VERSION/$ARTIFACT"
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

info "Downloading server package ($EDITION)..."
if ! curl -fsSL -o "$TMPDIR/$ARTIFACT" "$URL"; then
    die "Download failed. Check that $VERSION exists at https://github.com/$GITHUB_REPO/releases"
fi

# ── Unpack ───────────────────────────────────────────────────

if [ -d "$INSTALL_DIR" ] && [ "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    if [ "$FORCE" = "1" ]; then
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

# ── Run setup (pass license key and edition) ─────────────────

info "Running guided setup..."
OBSERVAL_INSTALL_DIR="$INSTALL_DIR" \
    OBSERVAL_LICENSE_KEY="$LICENSE_KEY" \
    OBSERVAL_EDITION="$EDITION" \
    bash "$INSTALL_DIR/setup.sh" </dev/tty
