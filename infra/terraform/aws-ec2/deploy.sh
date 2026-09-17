#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 Srihari <sriharilegend23@gmail.com>
# SPDX-License-Identifier: Apache-2.0
#
# Deploy Observal onto the EC2 instance provisioned by Terraform.
# Uses pre-built images from GHCR (no source builds required).
# Run this AFTER `terraform apply` completes.
#
# Usage: ./deploy.sh

set -euo pipefail

# ── Read Terraform outputs ───────────────────────────────────────────────────

INSTANCE_ID=$(terraform output -raw instance_id)
PUBLIC_IP=$(terraform output -raw public_ip)
REGION=$(terraform output -raw region)
DOMAIN=$(terraform output -raw domain)
IMAGE_TAG=$(terraform output -raw image_tag)
OBSERVAL_REF=$(terraform output -raw observal_ref)
OBSERVAL_REPO=$(terraform output -raw observal_repo)
ENV_OVERRIDES=$(terraform output -json env_overrides 2>/dev/null || echo "{}")
OBSERVABILITY_STACK=$(terraform output -raw observability_stack 2>/dev/null || echo "none")

echo "=== Observal EC2 Deploy ==="
echo "  Instance:  $INSTANCE_ID"
echo "  IP:        $PUBLIC_IP"
echo "  Region:    $REGION"
echo "  Domain:    ${DOMAIN:-"(none — HTTP only)"}"
echo "  Image:     ghcr.io/observal/observal-api:$IMAGE_TAG"
echo "  Observability: $OBSERVABILITY_STACK"
echo ""

# ── Helper: run command on instance via SSM ──────────────────────────────────

run_remote() {
  local cmd="$1"
  local timeout="${2:-600}"

  local cmd_id
  cmd_id=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters "{\"commands\":[\"$cmd\"]}" \
    --timeout-seconds "$timeout" \
    --region "$REGION" \
    --query "Command.CommandId" \
    --output text)

  # Poll for completion
  local status="InProgress"
  while [ "$status" = "InProgress" ] || [ "$status" = "Pending" ]; do
    sleep 5
    status=$(aws ssm get-command-invocation \
      --command-id "$cmd_id" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --query "Status" \
      --output text 2>/dev/null || echo "InProgress")
  done

  if [ "$status" != "Success" ]; then
    echo "ERROR: Command failed with status: $status"
    aws ssm get-command-invocation \
      --command-id "$cmd_id" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --query "StandardErrorContent" \
      --output text 2>/dev/null || true
    return 1
  fi

  # Print output
  aws ssm get-command-invocation \
    --command-id "$cmd_id" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --query "StandardOutputContent" \
    --output text 2>/dev/null || true
}

# ── Wait for SSM agent to come online ────────────────────────────────────────

echo "Waiting for instance to be reachable via SSM..."
for i in $(seq 1 60); do
  online=$(aws ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
    --region "$REGION" \
    --query "InstanceInformationList[0].PingStatus" \
    --output text 2>/dev/null || echo "None")
  if [ "$online" = "Online" ]; then
    echo "  SSM agent online."
    break
  fi
  if [ "$i" = "60" ]; then
    echo "ERROR: Instance not reachable via SSM after 5 minutes."
    exit 1
  fi
  sleep 5
done

# ── Wait for startup script to finish ────────────────────────────────────────

echo "Waiting for instance startup script to complete..."
for i in $(seq 1 60); do
  result=$(run_remote "test -f /var/run/observal-startup-complete && echo done || echo waiting" 30 2>/dev/null || echo "waiting")
  if echo "$result" | grep -q "done"; then
    echo "  Startup complete."
    break
  fi
  if [ "$i" = "60" ]; then
    echo "ERROR: Startup script did not complete after 5 minutes."
    exit 1
  fi
  sleep 5
done

# ── Deploy server package (pre-built images from GHCR) ───────────────────────

echo "Setting up Observal server package..."

# Clone the package plus bind-mounted configuration files that the release
# archive normally places beside docker-compose.yml.
run_remote "rm -rf /opt/observal /opt/observal-src && git clone --depth 1 --branch $OBSERVAL_REF $OBSERVAL_REPO /opt/observal-src && mkdir -p /opt/observal && cp /opt/observal-src/docker/server-package/* /opt/observal/ && cp /opt/observal-src/docker/nginx.conf /opt/observal/ && cp -r /opt/observal-src/grafana /opt/observal/ && rm -rf /opt/observal-src"

# ── Configure .env and secrets ───────────────────────────────────────────────

echo "Configuring environment..."
FRONTEND_URL="${DOMAIN:+https://$DOMAIN}"
FRONTEND_URL="${FRONTEND_URL:-http://$PUBLIC_IP}"

# The packaged installer owns secret generation and the file-backed .env layout.
# Host nginx is the only public listener. The compose stack remains bound to
# loopback so PostgreSQL, Redis, and DuckDB are never exposed with the web app.
BIND_ADDRESS="127.0.0.1"
API_HOST_PORT="8000"
run_remote "cd /opt/observal && sed -i 's/^OBSERVAL_VERSION=.*/OBSERVAL_VERSION=$IMAGE_TAG/' env.template && printf '\nAPI_HOST_PORT=$API_HOST_PORT\n' >> env.template && printf '%s\n%s\n%s\n' '$FRONTEND_URL' '$BIND_ADDRESS' '$OBSERVABILITY_STACK' | bash setup.sh" 1200

# Apply env overrides (skip empty values)
while IFS='=' read -r key value; do
  [ -z "$key" ] && continue
  [ -z "$value" ] && continue
  run_remote "cd /opt/observal && sed -i \"s|${key}=.*|${key}=${value}|\" .env || echo '${key}=${value}' >> .env"
done < <(echo "$ENV_OVERRIDES" | python3 -c "import sys,json; [print(f'{k}={v}') for k,v in json.load(sys.stdin).items()]" 2>/dev/null || true)

# ── Configure TLS (if domain set) ───────────────────────────────────────────

SERVER_NAME="${DOMAIN:-_}"
NGINX_PROXY_CONFIG=$(printf '%s\n' \
  'server {' \
  '    listen 80;' \
  "    server_name $SERVER_NAME;" \
  '    location / {' \
  '        proxy_pass http://127.0.0.1:8000;' \
  '        proxy_set_header Host $host;' \
  '        proxy_set_header X-Real-IP $remote_addr;' \
  '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
  '        proxy_set_header X-Forwarded-Proto $scheme;' \
  '        proxy_http_version 1.1;' \
  '        proxy_set_header Upgrade $http_upgrade;' \
  '        proxy_set_header Connection "upgrade";' \
  '    }' \
  '}' | base64 | tr -d '\n')
run_remote "apt-get update && apt-get install -y nginx && echo '$NGINX_PROXY_CONFIG' | base64 -d > /etc/nginx/sites-available/observal && ln -sf /etc/nginx/sites-available/observal /etc/nginx/sites-enabled/observal && rm -f /etc/nginx/sites-enabled/default && nginx -t && systemctl enable --now nginx" 1200
if [ -n "$DOMAIN" ]; then
  echo "Obtaining TLS certificate for $DOMAIN..."
  run_remote "apt-get install -y python3-certbot-nginx && certbot --nginx -d $DOMAIN --non-interactive --agree-tos --redirect -m admin@$DOMAIN" 1200
fi

# ── Apply final configuration ───────────────────────────────────────────────

COMPOSE_FILES="-f docker-compose.yml"
COMPOSE_PROFILE_ARGS=""
if [ "$OBSERVABILITY_STACK" != "none" ]; then
  COMPOSE_FILES="$COMPOSE_FILES -f docker-compose.observability.yml"
fi
if [ "$OBSERVABILITY_STACK" = "grafana" ]; then
  COMPOSE_PROFILE_ARGS="--profile grafana"
fi

echo "Applying environment overrides..."
run_remote "cd /opt/observal && docker compose $COMPOSE_PROFILE_ARGS $COMPOSE_FILES --env-file .env up -d --wait --wait-timeout 300" 1200

# ── Health check ─────────────────────────────────────────────────────────────

echo "Waiting for Observal to become healthy..."
URL="${DOMAIN:+https://$DOMAIN}"
URL="${URL:-http://$PUBLIC_IP}"

for i in $(seq 1 40); do
  status=$(curl -sf -o /dev/null -w "%{http_code}" "$URL/readyz" 2>/dev/null || echo "000")
  if [ "$status" = "200" ]; then
    echo ""
    echo "=== Observal is live ==="
    echo "  URL: $URL"
    echo "  SSM: aws ssm start-session --target $INSTANCE_ID --region $REGION"
    echo ""
    echo "  Default login: super@demo.example / super-changeme"
    echo ""
    exit 0
  fi
  printf "."
  sleep 15
done

echo ""
echo "WARNING: Health check did not pass within 10 minutes."
echo "Services may still be starting. Check with:"
echo "  aws ssm start-session --target $INSTANCE_ID --region $REGION"
echo "  sudo docker compose -f /opt/observal/docker-compose.yml ps"
echo ""
exit 1
