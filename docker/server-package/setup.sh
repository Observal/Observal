#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

set -euo pipefail

# Observal Server Setup
# Guides through initial configuration and starts the Docker Compose stack.
# Respects OBSERVAL_LICENSE_KEY and OBSERVAL_EDITION from the parent installer.

INSTALL_DIR="${OBSERVAL_INSTALL_DIR:-/opt/observal}"
ENV_FILE="$INSTALL_DIR/.env"
COMPOSE_FILE="$INSTALL_DIR/docker-compose.yml"

# License key passed from install-server.sh or set directly
LICENSE_KEY="${OBSERVAL_LICENSE_KEY:-}"
EDITION="${OBSERVAL_EDITION:-community}"

# Ed25519 public key for license verification
LICENSE_PUBLIC_KEY="X5Ia46wxT2AxZ6nFlvFnT7ZE6vXoVI208Io3TDoX6N8="

# ── Helpers ──────────────────────────────────────────────────

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }
die() {
    error "$@"
    exit 1
}

prompt_with_default() {
    local var_name="$1" prompt_text="$2" default="$3"
    local value
    printf '%s [%s]: ' "$prompt_text" "$default"
    read -r value
    value="${value:-$default}"
    eval "$var_name=\"\$value\""
}

prompt_secret() {
    local var_name="$1" prompt_text="$2" default="$3"
    local value
    if [ -n "$default" ]; then
        printf '%s [auto-generated]: ' "$prompt_text"
    else
        printf '%s: ' "$prompt_text"
    fi
    read -r value
    value="${value:-$default}"
    eval "$var_name=\"\$value\""
}

generate_secret() {
    python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null ||
        openssl rand -base64 32 2>/dev/null ||
        head -c 32 /dev/urandom | base64
}

# NOTE: This function is identical in install.sh, install-server.sh, and
# docker/server-package/setup.sh. If you change the validation logic,
# update all three files together.
validate_license() {
    local key="$1"

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

# ── Pre-flight ───────────────────────────────────────────────

command -v docker >/dev/null 2>&1 || die "Docker is required. Install: https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."

if [ -f "$ENV_FILE" ]; then
    warn "Existing .env found at $ENV_FILE"
    printf 'Overwrite? [y/N]: '
    read -r confirm
    [ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || {
        info "Keeping existing config. Run 'docker compose up -d' to start."
        exit 0
    }
fi

# ── License key prompt (if not already provided) ─────────────

if [ -z "$LICENSE_KEY" ]; then
    echo ""
    info "License key determines your edition:"
    info "  • With a valid key: Enterprise edition (SAML, SCIM, insights, self-learning)"
    info "  • Without a key:    Community edition (full open-source feature set)"
    echo ""
    printf 'Enterprise license key (leave blank for community): '
    read -r LICENSE_KEY

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
                warn "Cannot verify license locally (python3 cryptography not found)."
                warn "Proceeding with enterprise — the server will validate at startup."
                EDITION="enterprise"
            else
                die "Invalid license key. Check your key or contact support@observal.dev"
            fi
        fi
    else
        EDITION="community"
        info "Installing community edition"
    fi
fi

# ── Gather configuration ────────────────────────────────────

info "Observal Server Setup [$EDITION edition]"
echo ""

SECRET_KEY_DEFAULT=$(generate_secret)
POSTGRES_PW_DEFAULT=$(generate_secret | head -c 24)
CLICKHOUSE_PW_DEFAULT=$(generate_secret | head -c 24)

if [ "$EDITION" = "enterprise" ]; then
    LICENSE_PROMPT="Enterprise license key"
else
    LICENSE_PROMPT="Enterprise license key (leave blank for OSS)"
fi

prompt_with_default OBSERVAL_LICENSE_KEY "$LICENSE_PROMPT" ""
prompt_with_default FRONTEND_URL "Frontend URL (your public domain)" "http://localhost:3000"
prompt_secret SECRET_KEY "Secret key" "$SECRET_KEY_DEFAULT"
prompt_secret POSTGRES_PASSWORD "PostgreSQL password" "$POSTGRES_PW_DEFAULT"
prompt_secret CLICKHOUSE_PASSWORD "ClickHouse password" "$CLICKHOUSE_PW_DEFAULT"

echo ""

# ── Generate .env ────────────────────────────────────────────

info "Writing configuration to $ENV_FILE"

cp "$INSTALL_DIR/env.template" "$ENV_FILE"

sed -i.bak \
    -e "s|__SECRET_KEY__|$SECRET_KEY|g" \
    -e "s|__POSTGRES_PASSWORD__|$POSTGRES_PASSWORD|g" \
    -e "s|__CLICKHOUSE_PASSWORD__|$CLICKHOUSE_PASSWORD|g" \
    -e "s|__FRONTEND_URL__|$FRONTEND_URL|g" \
    "$ENV_FILE"
rm -f "$ENV_FILE.bak"

# Append license key if enterprise
if [ "$EDITION" = "enterprise" ] && [ -n "$LICENSE_KEY" ]; then
    echo "" >>"$ENV_FILE"
    echo "# Enterprise license key" >>"$ENV_FILE"
    echo "OBSERVAL_LICENSE_KEY=$LICENSE_KEY" >>"$ENV_FILE"
fi

chmod 600 "$ENV_FILE"

# ── Enterprise: authenticate to private registry ────────────

COMPOSE_FILES="-f docker-compose.yml"

if [ "$EDITION" = "enterprise" ]; then
    # Enterprise uses the enterprise compose overlay with ee/ services
    if [ -f "$INSTALL_DIR/docker-compose.enterprise.yml" ]; then
        COMPOSE_FILES="-f docker-compose.yml -f docker-compose.enterprise.yml"
        info "Enterprise compose overlay enabled."
    fi

    # Authenticate to private container registry if needed
    if echo "$LICENSE_KEY" | docker login ghcr.io -u observal-customer --password-stdin 2>/dev/null; then
        info "Authenticated with enterprise container registry."
    else
        warn "Could not authenticate with container registry. Enterprise images may not pull."
        warn "If you see pull errors, contact support@observal.dev"
    fi
fi

# ── Start services ───────────────────────────────────────────

info "Starting Observal services..."

cd "$INSTALL_DIR"
docker compose $COMPOSE_FILES --env-file .env up -d

info "Waiting for API to be healthy..."
for i in $(seq 1 60); do
    if docker compose $COMPOSE_FILES exec -T observal-api \
        python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')" 2>/dev/null; then
        break
    fi
    if [ "$i" -eq 60 ]; then
        die "API did not become healthy in 5 minutes. Check logs: docker compose $COMPOSE_FILES logs"
    fi
    sleep 5
done

# Restart LB to pick up new API container IP
docker compose $COMPOSE_FILES restart observal-lb
sleep 2

info ""
info "Observal is running! [$EDITION edition]"
info ""
info "  Dashboard:  $FRONTEND_URL"
info "  API:        ${FRONTEND_URL%:*}:8000"
info "  Grafana:    ${FRONTEND_URL%:*}:3001 (admin/admin)"
info ""
info "  Config:     $ENV_FILE"
info "  Start:      cd $INSTALL_DIR && docker compose $COMPOSE_FILES up -d"
info "  Stop:       cd $INSTALL_DIR && docker compose $COMPOSE_FILES down"
info "  Logs:       cd $INSTALL_DIR && docker compose $COMPOSE_FILES logs -f"
info ""
if [ "$EDITION" = "enterprise" ]; then
    info "Enterprise features: SAML, SCIM, insights, self-learning"
    info "Manage license: observal admin settings"
fi
info ""
info "Login:  $FRONTEND_URL"
info "  Email:    super@demo.example"
info "  Password: super-changeme"
