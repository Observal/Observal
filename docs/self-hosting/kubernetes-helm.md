<!-- SPDX-FileCopyrightText: 2026 Ravi Chopra <shivamchopra1234567890@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 amogh-dongre <amoghdongre16@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Rishank Jain <rishankj749@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Kubernetes Deployment with Helm

Deploy Observal onto a Kubernetes cluster using the official Helm chart.

> [!WARNING]
> **Production Notice**: The in-cluster PostgreSQL, ClickHouse, and Redis StatefulSets deployed by this chart are intended for evaluation, development, and small-scale testing. For production workloads, set `postgresql.enabled=false`, `clickhouse.enabled=false`, and `redis.enabled=false`, then provide `postgresql.externalUrl`, `clickhouse.externalUrl`, and `redis.externalUrl` for dedicated external services.

## Prerequisites

- Kubernetes cluster v1.27 or higher
- `helm` v3.8.0 or higher installed
- `kubectl` configured to access your cluster
- Ingress controller (e.g., `ingress-nginx`) installed on the cluster
- Default `StorageClass` supporting dynamic volume provisioning (PV/PVC)

## Quick Start

Use the hosted OCI chart after the first release that includes Helm chart publishing has completed:

1. Install the chart into a dedicated namespace:
   ```bash
   kubectl create namespace observal
   helm install observal oci://ghcr.io/observal/charts/observal \
     --version <version> \
     --namespace observal
   ```

2. Verify all workloads are running and completed:
   ```bash
   kubectl get pods -n observal
   ```

## Local Chart Development

To test unreleased chart changes directly from a clone:

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
helm install observal oci://ghcr.io/observal/charts/observal \
  --version <version> \
  --namespace observal \
  -f custom-values.yaml
```

### Parameters Reference Table

| Parameter | Description | Default |
| --- | --- | --- |
| `global.imageRegistry` | Global image registry prefix | `""` |
| `global.imagePullSecrets` | Global image pull secrets list | `[]` |
| `api.image.repository` | API container image repository | `ghcr.io/observal/observal-api` |
| `api.image.tag` | API container image tag. Defaults to the chart app version when empty. | `""` |
| `api.replicas` | Replicas for API deployment | `1` |
| `api.workers` | Uvicorn worker count per API pod | `2` |
| `worker.image.repository` | Worker container image repository | `ghcr.io/observal/observal-api` |
| `worker.image.tag` | Worker container image tag. Defaults to the chart app version when empty. | `""` |
| `worker.replicas` | Replicas for background job worker | `1` |
| `web.image.repository` | Web UI container image repository | `ghcr.io/observal/observal-web` |
| `web.image.tag` | Web UI container image tag. Defaults to the chart app version when empty. | `""` |
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
| `podDisruptionBudget.api.enabled` | Create a PodDisruptionBudget for API pods | `true` |
| `podDisruptionBudget.api.minAvailable` | Minimum available API pods during voluntary disruptions (integer or percentage) | `1` |
| `podDisruptionBudget.worker.enabled` | Create a PodDisruptionBudget for worker pods | `true` |
| `podDisruptionBudget.worker.minAvailable` | Minimum available worker pods during voluntary disruptions (integer or percentage) | `1` |
| `networkPolicy.enabled` | Create NetworkPolicies for API and worker pods (requires a CNI that enforces them) | `false` |
| `networkPolicy.ingressController.namespaceSelector` | Namespace of the ingress controller allowed to reach the API | `kubernetes.io/metadata.name: ingress-nginx` |
| `networkPolicy.ingressController.podSelector` | Ingress controller pods allowed to reach the API | `app.kubernetes.io/name: ingress-nginx` |
| `networkPolicy.dns.namespaceSelector` | Namespace of cluster DNS reachable from the worker | `kubernetes.io/metadata.name: kube-system` |
| `networkPolicy.dns.podSelector` | Cluster DNS pods reachable from the worker | `k8s-app: kube-dns` |
| `networkPolicy.kubeApiServer.cidrs` | Kubernetes API endpoint CIDRs reachable from the worker on TCP 443 and 6443. Required when `networkPolicy.enabled=true`. | `[]` |
| `networkPolicy.api.extraIngress` | Additional ingress rules for API pods | `[]` |
| `networkPolicy.worker.extraEgress` | Additional egress rules for worker pods | `[]` |

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
helm upgrade --install observal oci://ghcr.io/observal/charts/observal \
  --version <version> \
  --namespace observal \
  --set ingress.enabled=true \
  --set ingress.host=observal.mycompany.com \
  --set ingress.tls.enabled=true \
  --set ingress.tls.secretName=observal-tls \
  --set ingress.tls.certManager.enabled=true \
  --set ingress.tls.certManager.issuerName=letsencrypt-prod
```

## Network Policies

Set `networkPolicy.enabled=true` to create NetworkPolicies for the API and worker pods. They take effect only on clusters whose CNI enforces NetworkPolicy (for example Calico or Cilium). Other pods in the release are not selected and keep their current connectivity.

**API pods** accept traffic on port 8000 only from:

- the release's web pods, which proxy `/api/`, `/health`, and `/.well-known/` to the API
- the ingress controller pods matched by `networkPolicy.ingressController`
- any rules in `networkPolicy.api.extraIngress`

API egress is not restricted, because the API also calls identity providers, Git hosts, webhooks, and LLM model catalogs.

The ingress controller defaults match the upstream `ingress-nginx` chart installed in the `ingress-nginx` namespace. Point them at your controller's namespace and pod labels, or set both selectors to `null` to allow only the web pods and `extraIngress`. A controller running with `hostNetwork`, or a cloud load balancer that sends traffic directly to pod IPs, cannot be matched by pod selectors; allow its source addresses with an `ipBlock` in `extraIngress`. The same applies to a Prometheus instance scraping the API's `/metrics` endpoint.

**Worker pods** accept no inbound traffic, and may only connect to:

- cluster DNS on port 53 (UDP and TCP), matched by `networkPolicy.dns`
- the in-cluster PostgreSQL (5432), ClickHouse (8123), and Redis (6379) pods, for each datastore that is enabled
- the Kubernetes API endpoints in `networkPolicy.kubeApiServer.cidrs`, on TCP 443 and 6443, which the worker's `wait-for-init` initContainer polls before the worker starts
- any rules in `networkPolicy.worker.extraEgress`

`networkPolicy.kubeApiServer.cidrs` is required when NetworkPolicy is enabled; the chart fails to render without it rather than leaving worker pods stuck in `Init`. The `kubernetes` Service can be backed by several EndpointSlices, so select them by their `kubernetes.io/service-name` label to list every endpoint address:

```bash
kubectl get endpointslices \
  -n default \
  -l kubernetes.io/service-name=kubernetes \
  -o jsonpath='{range .items[*].endpoints[*].addresses[*]}{.}{"\n"}{end}'
```

Add each IPv4 address as a `/32` CIDR and each IPv6 address as a `/128` CIDR, for example `10.0.0.1/32` or `fd00::1/128`.

Update the CIDRs if your control plane endpoints change, which can happen during managed cluster upgrades. If your API server listens on another port, allow it through `networkPolicy.worker.extraEgress`. Some CNIs do not match Kubernetes API traffic by `ipBlock` (Cilium, for example, identifies it as the `kube-apiserver` entity); on those, allow it with a CNI-specific policy.

The worker also runs Git source sync, alert webhooks, insight report generation through your LLM provider, and usage reporting. With NetworkPolicy enabled, these are blocked until you allow their destinations in `networkPolicy.worker.extraEgress`. External PostgreSQL, ClickHouse, or Redis endpoints (`*.enabled=false`) must be added the same way. The chart does not derive rules from `*.externalUrl`.

```yaml
networkPolicy:
  enabled: true
  kubeApiServer:
    cidrs:
      - 10.0.0.1/32
  worker:
    extraEgress:
      # Managed PostgreSQL
      - to:
          - ipBlock:
              cidr: 10.20.0.0/24
        ports:
          - protocol: TCP
            port: 5432
      # Public HTTPS: Git hosts, webhooks, LLM providers, usage reporting
      - to:
          - ipBlock:
              cidr: 0.0.0.0/0
              except:
                - 10.0.0.0/8
                - 172.16.0.0/12
                - 192.168.0.0/16
        ports:
          - protocol: TCP
            port: 443
```

## Pod Disruption Budgets

PodDisruptionBudgets for the API and worker are created by default with `minAvailable: 1`. They limit voluntary evictions such as `kubectl drain` and node pool upgrades; they do not affect Deployment rolling updates.

With the default single replica, a budget of `minAvailable: 1` allows no evictions, so draining the node that runs the pod waits until the budget can be met. Before node maintenance, raise `api.replicas` and `worker.replicas`, lower `minAvailable`, or disable the budget with `podDisruptionBudget.api.enabled=false` / `podDisruptionBudget.worker.enabled=false`. The API and worker share the `apidata` ReadWriteOnce volume, so additional replicas must be scheduled on the same node unless the volume's storage class supports multi-node access.

## Maintenance & Operations

### Upgrading

To apply configuration changes or update to a newer chart version:

```bash
helm upgrade observal oci://ghcr.io/observal/charts/observal \
  --version <version> \
  --namespace observal \
  -f custom-values.yaml
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

## Chart Publishing

Official releases publish the Helm chart as an OCI artifact to GitHub Container Registry:

```text
oci://ghcr.io/observal/charts/observal
```

Helm OCI registries do not use `helm repo add`; install and upgrade commands reference the `oci://` chart URL directly.

After the first release publishes the package, make the GHCR chart package public in the repository package settings if it is not already public.

ArtifactHub should be registered against the OCI chart URL. OCI repositories require one ArtifactHub repository per chart. The release workflow pushes `infra/helm/artifacthub-repo.yml` to GHCR with the special `artifacthub.io` tag. After ArtifactHub creates the repository record, copy the repository ID from the ArtifactHub control panel into `infra/helm/artifacthub-repo.yml` as `repositoryID` to enable Verified Publisher status on the next chart release.
