<!-- SPDX-FileCopyrightText: 2026 Observal Contributors -->
<!-- SPDX-FileCopyrightText: 2026 amogh-dongre <amoghdongre16@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Observal

Observal is an agent-centric registry and observability platform for AI coding agents. This chart deploys the API, web UI, worker, PostgreSQL, DuckDB analytics, Redis, and supporting Kubernetes resources for self-hosted installations.

## Install

After the hosted OCI chart has been published:

```bash
kubectl create namespace observal
helm install observal oci://ghcr.io/observal/charts/observal \
  --version <version> \
  --namespace observal
```

For production deployments, use managed PostgreSQL and Redis services by setting `postgresql.enabled=false` and `redis.enabled=false`, then providing the matching external connection URLs. The analytics store is a DuckDB singleton and always runs in-cluster: give it a `ReadWriteOnce` volume and never scale it past one replica.

See the Kubernetes deployment guide for the full values reference and operational notes:

https://github.com/Observal/Observal/blob/main/docs/self-hosting/kubernetes-helm.md
