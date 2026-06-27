#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

set -euo pipefail

# Observal CLI Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/Observal/Observal/main/install.sh | bash -s -- [OPTIONS]
#
# Options:
#   --license-key KEY          Enterprise license key (enables enterprise edition)
#   --version VERSION          Version to install (default: latest)
#   --bin-dir DIR              Install directory (default: /usr/local/bin)
#
# Environment variable overrides (lower priority than flags):
#   OBSERVAL_LICENSE_KEY       Enterprise license key
#   OBSERVAL_VERSION=latest    Version to install
#   OBSERVAL_BIN_DIR=/path     Install directory

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
BIN_DIR="${OBSERVAL_BIN_DIR:-/usr/local/bin}"
BASE_URL="${OBSERVAL_BASE_URL:-}" # Override for testing (e.g. http://localhost:9999)

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
    --bin-dir)
        [ -n "${2:-}" ] || die "--bin-dir requires a value"
        BIN_DIR="$2"
        shift 2
        ;;
    --bin-dir=*)
        BIN_DIR="${1#--bin-dir=}"
        shift
        ;;
    -h | --help)
        cat <<'HELP'
Observal CLI Installer
Usage: curl -fsSL https://raw.githubusercontent.com/Observal/Observal/main/install.sh | bash -s -- [OPTIONS]

Options:
  --license-key KEY   Enterprise license key (enables enterprise edition)
  --version VERSION   Version to install (default: latest)
  --bin-dir DIR       Install directory (default: /usr/local/bin)

Environment variable overrides (lower priority than flags):
  OBSERVAL_LICENSE_KEY   Enterprise license key
  OBSERVAL_VERSION       Version to install
  OBSERVAL_BIN_DIR       Install directory
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

    # Verify signature and check expiry using Python (available on macOS and most Linux)
    python3 - "$payload_b64" "$sig_b64" "$LICENSE_PUBLIC_KEY" 2>/dev/null <<'PYTHON'
import base64, json, sys, time

payload_b64, sig_b64, pub_key_b64 = sys.argv[1], sys.argv[2], sys.argv[3]

# Always do structural validation (no dependencies needed)
try:
    padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded))
except Exception:
    # Payload isn't valid base64 JSON — definitely invalid
    sys.exit(1)

if "org_id" not in payload:
    sys.exit(1)

# Check expiry (works without cryptography)
exp = payload.get("exp", 0)
if exp > 0 and time.time() > exp:
    print("EXPIRED", file=sys.stderr)
    sys.exit(2)

# Try full signature verification if cryptography is available
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pub_key_bytes = base64.urlsafe_b64decode(pub_key_b64 + "==")
    pub_key = Ed25519PublicKey.from_public_bytes(pub_key_bytes)
    sig_bytes = base64.urlsafe_b64decode(sig_b64 + "==")
    pub_key.verify(sig_bytes, payload_b64.encode())

    # Fully verified
    print(payload.get("org_id", "unknown"))
    sys.exit(0)
except ImportError:
    # cryptography not available — structure is valid but signature unverified
    print(payload.get("org_id", "unknown"))
    sys.exit(3)
except Exception as e:
    # Signature mismatch
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

# ── Detect platform ──────────────────────────────────────────

detect_os() {
    case "$(uname -s)" in
    Linux*) echo "linux" ;;
    Darwin*) echo "macos" ;;
    MINGW* | MSYS* | CYGWIN*) echo "windows" ;;
    *) die "Unsupported OS: $(uname -s)" ;;
    esac
}

detect_arch() {
    case "$(uname -m)" in
    x86_64 | amd64) echo "x64" ;;
    aarch64 | arm64) echo "arm64" ;;
    *) die "Unsupported architecture: $(uname -m)" ;;
    esac
}

OS=$(detect_os)
ARCH=$(detect_arch)

# ── Resolve version ──────────────────────────────────────────

command -v curl >/dev/null 2>&1 || die "'curl' is required but not found."

if [ "$VERSION" = "latest" ]; then
    VERSION=$(curl -fsSL "https://api.github.com/repos/$GITHUB_REPO/releases/latest" |
        grep '"tag_name"' | head -1 | cut -d'"' -f4)
    [ -n "$VERSION" ] || die "Could not determine latest version"
fi

info "Installing Observal CLI $VERSION ($OS/$ARCH) [$EDITION edition]"

# ── Download and verify ──────────────────────────────────────

EXT=""
[ "$OS" = "windows" ] && EXT=".exe"

# Same binary for both editions; enterprise activates via the license key
# written to ~/.observal/config.json below.
ARTIFACT="observal-${OS}-${ARCH}${EXT}"

if [ -n "$BASE_URL" ]; then
    URL="${BASE_URL}/${ARTIFACT}"
    CHECKSUM_URL="${BASE_URL}/checksums.txt"
else
    URL="https://github.com/$GITHUB_REPO/releases/download/$VERSION/$ARTIFACT"
    CHECKSUM_URL="https://github.com/$GITHUB_REPO/releases/download/$VERSION/checksums.txt"
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

info "Downloading $ARTIFACT..."
if ! curl -fsSL -o "$TMPDIR/$ARTIFACT" "$URL"; then
    die "Download failed. Check that $VERSION exists at https://github.com/$GITHUB_REPO/releases"
fi

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

# ── Write license key to config ──────────────────────────────

if [ "$EDITION" = "enterprise" ] && [ -n "$LICENSE_KEY" ]; then
    CONFIG_DIR="${HOME}/.observal"
    mkdir -p "$CONFIG_DIR"
    CONFIG_FILE="$CONFIG_DIR/config.json"

    if [ -f "$CONFIG_FILE" ]; then
        # Merge license key into existing config
        OBSERVAL_KEY_VALUE="$LICENSE_KEY" python3 -c "
import json, os
try:
    with open('$CONFIG_FILE') as f:
        config = json.load(f)
except (json.JSONDecodeError, FileNotFoundError):
    config = {}
config['license_key'] = os.environ['OBSERVAL_KEY_VALUE']
with open('$CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2)
" 2>/dev/null || true
    else
        printf '{\n  "license_key": "%s"\n}\n' "$LICENSE_KEY" >"$CONFIG_FILE"
    fi
    chmod 600 "$CONFIG_FILE"
    info "License key saved to $CONFIG_FILE"
fi

# ── Done ─────────────────────────────────────────────────────

info "Installed observal ($EDITION) to $INSTALL_PATH"
info "Run 'observal --version' to verify."
if [ "$EDITION" = "enterprise" ]; then
    info "Enterprise features are active. Set OBSERVAL_LICENSE_KEY in your server .env as well."
fi
