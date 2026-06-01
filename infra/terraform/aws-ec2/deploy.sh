#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
#
# Deploy Observal onto the EC2 instance provisioned by Terraform.
# Run this AFTER `terraform apply` completes.
#
# Usage: ./deploy.sh

set -euo pipefail

# ── Read Terraform outputs ───────────────────────────────────────────────────

INSTANCE_ID=$(terraform output -raw instance_id)
PUBLIC_IP=$(terraform output -raw public_ip)
REGION=$(terraform output -raw region)
DOMAIN=$(terraform output -raw domain)
OBSERVAL_REF=$(terraform output -raw observal_ref)
OBSERVAL_REPO=$(terraform output -raw observal_repo)
ENV_OVERRIDES=$(terraform output -json env_overrides 2>/dev/null || echo "{}")

echo "=== Observal EC2 Deploy ==="
echo "  Instance:  $INSTANCE_ID"
echo "  IP:        $PUBLIC_IP"
echo "  Region:    $REGION"
echo "  Domain:    ${DOMAIN:-"(none — HTTP only)"}"
echo "  Ref:       $OBSERVAL_REF"
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

# ── Clone and checkout ───────────────────────────────────────────────────────

echo "Cloning Observal ($OBSERVAL_REF)..."
run_remote "rm -rf /opt/observal && git clone $OBSERVAL_REPO /opt/observal && cd /opt/observal && git checkout $OBSERVAL_REF"

# ── Configure .env ───────────────────────────────────────────────────────────

echo "Configuring environment..."
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || openssl rand -base64 32)

# Build sed commands for env overrides (skip empty values)
SED_CMDS="sed -i \"s|SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|\" .env"
while IFS='=' read -r key value; do
  [ -z "$key" ] && continue
  [ -z "$value" ] && continue
  SED_CMDS="$SED_CMDS && sed -i \"s|${key}=.*|${key}=${value}|\" .env"
done < <(echo "$ENV_OVERRIDES" | python3 -c "import sys,json; [print(f'{k}={v}') for k,v in json.load(sys.stdin).items()]" 2>/dev/null || true)

run_remote "cd /opt/observal && cp .env.example .env && $SED_CMDS"

# ── Configure nginx + TLS ────────────────────────────────────────────────────

if [ -n "$DOMAIN" ]; then
  echo "Configuring HTTPS for $DOMAIN..."
  run_remote "cd /opt/observal && sed -i 's/server_name .*/server_name $DOMAIN;/' docker/nginx.production.conf && sed -i 's|ssl_certificate .*|ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;|' docker/nginx.production.conf && sed -i 's|ssl_certificate_key .*|ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;|' docker/nginx.production.conf"

  echo "Obtaining TLS certificate..."
  run_remote "certbot certonly --standalone -d $DOMAIN --non-interactive --agree-tos -m admin@$DOMAIN"
else
  echo "No domain configured — setting up HTTP-only access..."
  # Replace nginx config with HTTP-only version
  run_remote "cd /opt/observal && cat > docker/nginx.production.conf << 'NGINXEOF'
upstream observal_api {
    server observal-api:8000;
}
upstream observal_web {
    server observal-web:3000;
}
server {
    listen 80;
    server_name _;

    location /api/ {
        proxy_pass http://observal_api;
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        proxy_read_timeout 600s;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \\\$http_upgrade;
        proxy_set_header Connection \"upgrade\";
    }
    location /health { proxy_pass http://observal_api; proxy_set_header Host \\\$host; }
    location /livez { proxy_pass http://observal_api; proxy_set_header Host \\\$host; }
    location /readyz { proxy_pass http://observal_api; proxy_set_header Host \\\$host; }
    location /graphql {
        proxy_pass http://observal_api;
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \\\$http_upgrade;
        proxy_set_header Connection \"upgrade\";
    }
    location /v1/ {
        proxy_pass http://observal_api;
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        client_max_body_size 10m;
    }
    location / {
        proxy_pass http://observal_web;
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \\\$http_upgrade;
        proxy_set_header Connection \"upgrade\";
    }
}
NGINXEOF"
fi

# ── Build and start ──────────────────────────────────────────────────────────

echo "Building Docker images (this takes 5-10 minutes on first run)..."
run_remote "cd /opt/observal && docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.production.yml build" 900

echo "Starting services..."
run_remote "cd /opt/observal && docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.production.yml up -d"

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
echo "The build may still be running. Check with:"
echo "  aws ssm start-session --target $INSTANCE_ID --region $REGION"
echo "  sudo docker ps"
echo ""
exit 1
