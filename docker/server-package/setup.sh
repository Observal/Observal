#!/usr/bin/env bash
set -euo pipefail

# Observal Server Setup
# Guides through initial configuration and starts the Docker Compose stack.

INSTALL_DIR="${OBSERVAL_INSTALL_DIR:-/opt/observal}"
ENV_FILE="$INSTALL_DIR/.env"
COMPOSE_FILE="$INSTALL_DIR/docker/docker-compose.yml"

# ── Helpers ──────────────────────────────────────────────────

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33mWARN:\033[0m %s\n' "$*"; }
error() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }
die()   { error "$@"; exit 1; }

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
  python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null \
    || openssl rand -base64 32 2>/dev/null \
    || head -c 32 /dev/urandom | base64
}

# ── Pre-flight ───────────────────────────────────────────────

command -v docker >/dev/null 2>&1 || die "Docker is required. Install: https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."

if [ -f "$ENV_FILE" ]; then
  warn "Existing .env found at $ENV_FILE"
  printf 'Overwrite? [y/N]: '
  read -r confirm
  [ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || { info "Keeping existing config. Run 'docker compose up -d' to start."; exit 0; }
fi

# ── Gather configuration ────────────────────────────────────

info "Observal Server Setup"
echo ""

SECRET_KEY_DEFAULT=$(generate_secret)
POSTGRES_PW_DEFAULT=$(generate_secret | head -c 24)
CLICKHOUSE_PW_DEFAULT=$(generate_secret | head -c 24)

prompt_with_default DEPLOYMENT_MODE "Deployment mode (local/enterprise)" "local"
prompt_with_default FRONTEND_URL "Frontend URL (your public domain)" "http://localhost:3000"
prompt_secret SECRET_KEY "Secret key" "$SECRET_KEY_DEFAULT"
prompt_secret POSTGRES_PASSWORD "PostgreSQL password" "$POSTGRES_PW_DEFAULT"
prompt_secret CLICKHOUSE_PASSWORD "ClickHouse password" "$CLICKHOUSE_PW_DEFAULT"

echo ""

# ── Generate .env ────────────────────────────────────────────

info "Writing configuration to $ENV_FILE"

cp "$INSTALL_DIR/docker/server-package/env.template" "$ENV_FILE"

sed -i.bak \
  -e "s|__SECRET_KEY__|$SECRET_KEY|g" \
  -e "s|__POSTGRES_PASSWORD__|$POSTGRES_PASSWORD|g" \
  -e "s|__CLICKHOUSE_PASSWORD__|$CLICKHOUSE_PASSWORD|g" \
  -e "s|__DEPLOYMENT_MODE__|$DEPLOYMENT_MODE|g" \
  -e "s|__FRONTEND_URL__|$FRONTEND_URL|g" \
  "$ENV_FILE"
rm -f "$ENV_FILE.bak"

chmod 600 "$ENV_FILE"

# ── Enterprise: authenticate to private registry ────────────

COMPOSE_FILES="-f docker/docker-compose.yml"

if [ "$DEPLOYMENT_MODE" = "enterprise" ]; then
  echo ""
  prompt_secret ENTERPRISE_TOKEN "Enterprise license token (leave blank to skip)" ""
  if [ -n "$ENTERPRISE_TOKEN" ]; then
    info "Authenticating with enterprise registry..."
    echo "$ENTERPRISE_TOKEN" | docker login ghcr.io -u observal-customer --password-stdin
    COMPOSE_FILES="-f docker/docker-compose.yml -f docker/docker-compose.enterprise.yml"
    info "Enterprise images will be used."
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
info "Observal is running!"
info ""
info "  Dashboard:  $FRONTEND_URL"
info "  API:        ${FRONTEND_URL%:*}:8000"
info "  Grafana:    ${FRONTEND_URL%:*}:3001 (admin/admin)"
info ""
info "  Config:     $ENV_FILE"
info "  Logs:       cd $INSTALL_DIR && docker compose -f docker/docker-compose.yml logs -f"
info "  Stop:       cd $INSTALL_DIR && docker compose -f docker/docker-compose.yml down"
info ""
info "Next: create your first admin account at $FRONTEND_URL"
