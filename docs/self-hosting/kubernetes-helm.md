<!-- SPDX-FileCopyrightText: 2026 Ravi Chopra <shivamchopra1234567890@gmail.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-only -->

# Kubernetes Deployment with Helm

Deploy Observal onto a Kubernetes cluster using the official Helm chart located in `infra/helm/observal`.

> [!WARNING]
> **Production Notice**: The in-cluster PostgreSQL, ClickHouse, and Redis StatefulSets deployed by this chart are intended for evaluation, development, and small-scale testing. For production workloads, set `postgresql.enabled=false`, `clickhouse.enabled=false`, and `redis.enabled=false`, then provide `postgresql.externalUrl`, `clickhouse.externalUrl`, and `redis.externalUrl` for managed services such as AWS RDS, Cloud SQL, ClickHouse Cloud, or ElastiCache.

## Prerequisites

- Kubernetes cluster v1.27 or higher
- `helm` v3.8.0 or higher installed
- `kubectl` configured to access your cluster
- Ingress controller (e.g., `ingress-nginx`) installed on the cluster
- Default `StorageClass` supporting dynamic volume provisioning (PV/PVC)

## Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/Observal/Observal.git
   cd Observal
   ```

2. Install the chart into a dedicated namespace:
   ```bash
   kubectl create namespace observal
   helm install observal ./infra/helm/observal --namespace observal
   ```

3. Verify all workloads are running and completed:
   ```bash
   kubectl get pods -n observal
   ```

## Configuration

You can customize the deployment by passing a custom values file (`-f values.yaml`) or setting flags via `--set`.

```bash
helm install observal ./infra/helm/observal --namespace observal -f custom-values.yaml
```

### Parameters Reference Table

| Parameter | Description | Default |
| --- | --- | --- |
| `global.imageRegistry` | Global image registry prefix | `""` |
| `global.imagePullSecrets` | Global image pull secrets list | `[]` |
| `api.image.repository` | API container image repository | `ghcr.io/observal/observal-api` |
| `api.image.tag` | API container image tag | `latest` |
| `api.replicas` | Replicas for API deployment | `1` |
| `api.workers` | Uvicorn worker count per API pod | `2` |
| `worker.replicas` | Replicas for background job worker | `1` |
| `web.replicas` | Replicas for Web UI deployment | `1` |
| `postgresql.enabled` | Deploy embedded PostgreSQL StatefulSet | `true` |
| `postgresql.externalUrl` | PostgreSQL URL used when embedded PostgreSQL is disabled | `""` |
| `postgresql.storage.size` | PVC size for PostgreSQL | `10Gi` |
| `clickhouse.enabled` | Deploy embedded ClickHouse StatefulSet | `true` |
| `clickhouse.externalUrl` | ClickHouse URL used when embedded ClickHouse is disabled | `""` |
| `clickhouse.storage.size` | PVC size for ClickHouse | `50Gi` |
| `redis.enabled` | Deploy embedded Redis StatefulSet | `true` |
| `redis.externalUrl` | Redis URL used when embedded Redis is disabled | `""` |
| `redis.storage.size` | PVC size for Redis | `2Gi` |
| `ingress.enabled` | Enable Kubernetes Ingress resource | `true` |
| `ingress.host` | Hostname for Ingress rule | `observal.example.com` |
| `ingress.tls.enabled` | Enable TLS termination on Ingress | `false` |
| `ingress.tls.certManager.enabled` | Automatically request cert via cert-manager | `false` |
| `secrets.existingSecret` | Use pre-existing K8s Secret for credentials | `""` |
| `secrets.secretKey` | Override generated application secret | `""` |
| `config.logLevel` | Application log level (`DEBUG`, `INFO`, `WARN`, `ERROR`) | `INFO` |
| `config.seedDemoAccounts` | Seed demo accounts on startup | `false` |

## Accessing the Application

### Via Port Forwarding (Development/Testing)

To access the Web UI locally without configuring Ingress DNS:

```bash
kubectl port-forward svc/observal-web 3000:3000 -n observal
```

Open `http://localhost:3000` in your browser.

### Via Ingress & TLS (Production)

Enable ingress and configure TLS termination using `cert-manager`:

```bash
helm upgrade --install observal ./infra/helm/observal \
  --namespace observal \
  --set ingress.enabled=true \
  --set ingress.host=observal.mycompany.com \
  --set ingress.tls.enabled=true \
  --set ingress.tls.secretName=observal-tls \
  --set ingress.tls.certManager.enabled=true \
  --set ingress.tls.certManager.issuerName=letsencrypt-prod
```

## Maintenance & Operations

### Upgrading

To apply configuration changes or update to a newer chart version:

```bash
helm upgrade observal ./infra/helm/observal --namespace observal -f custom-values.yaml
```

### Rollback

If an upgrade encounters issues, rollback to a previous release revision:

```bash
# View release history
helm history observal --namespace observal

# Rollback to revision 1
helm rollback observal 1 --namespace observal
```

### Uninstalling

To delete the deployment and associated Kubernetes resources:

```bash
helm uninstall observal --namespace observal
```

> [!NOTE]
> Persistent Volume Claims (PVCs) for PostgreSQL, ClickHouse, Redis, and API data are retained by default to prevent accidental data loss. To delete them permanently, execute: `kubectl delete pvc -l app.kubernetes.io/instance=observal -n observal`.
