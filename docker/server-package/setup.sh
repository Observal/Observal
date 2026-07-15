#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

# Observal Server Setup
# Guides through initial configuration and starts the Docker Compose stack.

INSTALL_DIR="${OBSERVAL_INSTALL_DIR:-/opt/observal}"
ENV_FILE="$INSTALL_DIR/.env"
COMPOSE_FILE="$INSTALL_DIR/docker-compose.yml"


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

prompt_observability_stack() {
    local value
    while true; do
        printf 'Bundled observability stack (none, prometheus, grafana) [none]: '
        read -r value
        value="${value:-none}"
        case "$value" in
            none | prometheus | grafana)
                OBSERVABILITY_STACK="$value"
                return 0
                ;;
            *)
                warn "Choose one of: none, prometheus, grafana"
                ;;
        esac
    done
}

generate_secret() {
    python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null ||
        openssl rand -base64 32 2>/dev/null ||
        head -c 32 /dev/urandom | base64
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

# ── Gather configuration ────────────────────────────────────

info "Observal Server Setup"
echo ""

SECRET_KEY_DEFAULT=$(generate_secret)
POSTGRES_PW_DEFAULT=$(generate_secret | head -c 24)
CLICKHOUSE_PW_DEFAULT=$(generate_secret | head -c 24)
GRAFANA_PW_DEFAULT=$(generate_secret | head -c 24)

prompt_with_default FRONTEND_URL "Frontend URL (your public domain)" "http://localhost:3000"
prompt_secret SECRET_KEY "Secret key" "$SECRET_KEY_DEFAULT"
prompt_secret POSTGRES_PASSWORD "PostgreSQL password" "$POSTGRES_PW_DEFAULT"
prompt_secret CLICKHOUSE_PASSWORD "ClickHouse password" "$CLICKHOUSE_PW_DEFAULT"
prompt_observability_stack
if [ "$OBSERVABILITY_STACK" = "grafana" ]; then
    prompt_secret GRAFANA_ADMIN_PASSWORD "Grafana admin password" "$GRAFANA_PW_DEFAULT"
fi

echo ""

# ── Generate .env ────────────────────────────────────────────

info "Writing configuration to $ENV_FILE"

cp "$INSTALL_DIR/env.template" "$ENV_FILE"

sed -i.bak \
    -e "s|__SECRET_KEY__|$SECRET_KEY|g" \
    -e "s|__POSTGRES_PASSWORD__|$POSTGRES_PASSWORD|g" \
    -e "s|__CLICKHOUSE_PASSWORD__|$CLICKHOUSE_PASSWORD|g" \
    "$ENV_FILE"
rm -f "$ENV_FILE.bak"


if [ "$OBSERVABILITY_STACK" = "grafana" ]; then
    echo "" >>"$ENV_FILE"
    echo "# Optional bundled observability" >>"$ENV_FILE"
    echo "GRAFANA_ADMIN_USER=admin" >>"$ENV_FILE"
    echo "GRAFANA_ADMIN_PASSWORD=$GRAFANA_ADMIN_PASSWORD" >>"$ENV_FILE"
fi

chmod 600 "$ENV_FILE"

COMPOSE_FILES="-f docker-compose.yml"
COMPOSE_PROFILE_ARGS=""

if [ "$OBSERVABILITY_STACK" != "none" ]; then
    if [ -f "$INSTALL_DIR/docker-compose.observability.yml" ]; then
        COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.observability.yml"
        info "Bundled observability stack enabled: $OBSERVABILITY_STACK"
    else
        die "docker-compose.observability.yml is missing from $INSTALL_DIR"
    fi
fi

if [ "$OBSERVABILITY_STACK" = "grafana" ]; then
    COMPOSE_PROFILE_ARGS="--profile grafana"
fi

# ── Start services ───────────────────────────────────────────

info "Starting Observal services..."

cd "$INSTALL_DIR"
docker compose $COMPOSE_PROFILE_ARGS $COMPOSE_FILES --env-file .env up -d

info "Waiting for API to be healthy..."
for i in $(seq 1 60); do
    if docker compose $COMPOSE_PROFILE_ARGS $COMPOSE_FILES exec -T observal-api \
        python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')" 2>/dev/null; then
        break
    fi
    if [ "$i" -eq 60 ]; then
        die "API did not become healthy in 5 minutes. Check logs: docker compose $COMPOSE_PROFILE_ARGS $COMPOSE_FILES logs"
    fi
    sleep 5
done

# Restart LB to pick up new API container IP
docker compose $COMPOSE_PROFILE_ARGS $COMPOSE_FILES restart observal-lb
sleep 2

info ""
info "Observal is running! [$EDITION edition]"
info ""
info "  Dashboard:  $FRONTEND_URL"
info "  API:        ${FRONTEND_URL%:*}:8000"
if [ "$OBSERVABILITY_STACK" = "grafana" ]; then
    info "  Grafana:    ${FRONTEND_URL%:*}:3001 (admin/$GRAFANA_ADMIN_PASSWORD)"
fi
info ""
info "  Config:     $ENV_FILE"
info "  Start:      cd $INSTALL_DIR && docker compose $COMPOSE_PROFILE_ARGS $COMPOSE_FILES up -d"
info "  Stop:       cd $INSTALL_DIR && docker compose $COMPOSE_PROFILE_ARGS $COMPOSE_FILES down"
info "  Logs:       cd $INSTALL_DIR && docker compose $COMPOSE_PROFILE_ARGS $COMPOSE_FILES logs -f"
info ""
info ""
info "Login:  $FRONTEND_URL"
info "  Email:    super@demo.example"
info "  Password: super-changeme"
