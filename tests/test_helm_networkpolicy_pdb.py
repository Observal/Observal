# SPDX-FileCopyrightText: 2026 Rishank Jain <rishankj749@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Rendered-manifest checks for the Helm chart's NetworkPolicies and PodDisruptionBudgets."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "infra/helm/observal"
HELM = shutil.which("helm")

pytestmark = pytest.mark.skipif(HELM is None, reason="helm is not installed")

SELECTOR = {"app.kubernetes.io/name": "observal", "app.kubernetes.io/instance": "observal"}
API_SERVER_CIDR = "10.0.0.1/32"
NETWORK_POLICY_ON = {"networkPolicy": {"enabled": True, "kubeApiServer": {"cidrs": [API_SERVER_CIDR]}}}
EXTERNAL_DATASTORES = {
    "postgresql": {"enabled": False, "externalUrl": "postgresql+asyncpg://u:p@pg.example.com:5432/observal"},
    "clickhouse": {"enabled": False, "externalUrl": "clickhouse://u:p@ch.example.com:8123/observal"},
    "redis": {"enabled": False, "externalUrl": "redis://redis.example.com:6379"},
}


def _run_helm(values: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [HELM, "template", "observal", str(CHART), "--namespace", "observal", "--values", "-"],
        input=yaml.safe_dump(values or {}),
        capture_output=True,
        text=True,
    )


def _render(values: dict | None = None) -> list[dict]:
    result = _run_helm(values)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _merge(*parts: dict) -> dict:
    merged: dict = {}
    for part in parts:
        for key, value in part.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = _merge(merged[key], value)
            else:
                merged[key] = value
    return merged


def _by_kind(docs: list[dict], kind: str) -> dict[str, dict]:
    return {doc["metadata"]["name"]: doc for doc in docs if doc["kind"] == kind}


def _component(component: str) -> dict:
    return {**SELECTOR, "app.kubernetes.io/component": component}


def _ports(rule: dict) -> set[tuple[str, int]]:
    return {(port["protocol"], port["port"]) for port in rule.get("ports", [])}


def _same_items(actual: list, expected: list) -> bool:
    return len(actual) == len(expected) and all(item in actual for item in expected)


def _egress_components(policy: dict) -> set[str]:
    return {
        peer["podSelector"]["matchLabels"]["app.kubernetes.io/component"]
        for rule in policy["spec"]["egress"]
        for peer in rule.get("to", [])
        if "podSelector" in peer and "namespaceSelector" not in peer
    }


def _dns_rules(policy: dict) -> list[dict]:
    return [rule for rule in policy["spec"]["egress"] if _ports(rule) == {("UDP", 53), ("TCP", 53)}]


def test_default_render_has_both_pdbs_and_no_network_policies():
    docs = _render()

    assert _by_kind(docs, "NetworkPolicy") == {}
    assert set(_by_kind(docs, "PodDisruptionBudget")) == {"observal-api", "observal-worker"}


@pytest.mark.parametrize("component", ["api", "worker"])
def test_pdb_selector_matches_deployment_selector(component):
    docs = _render()
    pdb = _by_kind(docs, "PodDisruptionBudget")[f"observal-{component}"]
    deployment = _by_kind(docs, "Deployment")[f"observal-{component}"]

    assert pdb["apiVersion"] == "policy/v1"
    assert pdb["spec"]["minAvailable"] == 1
    assert pdb["spec"]["selector"] == deployment["spec"]["selector"]
    pod_labels = deployment["spec"]["template"]["metadata"]["labels"]
    assert pdb["spec"]["selector"]["matchLabels"].items() <= pod_labels.items()


@pytest.mark.parametrize(("disabled", "remaining"), [("api", "worker"), ("worker", "api")])
def test_each_pdb_can_be_disabled(disabled, remaining):
    docs = _render({"podDisruptionBudget": {disabled: {"enabled": False}}})

    assert set(_by_kind(docs, "PodDisruptionBudget")) == {f"observal-{remaining}"}


def test_pdb_min_available_accepts_percentage():
    docs = _render({"podDisruptionBudget": {"api": {"minAvailable": "50%"}}})

    assert _by_kind(docs, "PodDisruptionBudget")["observal-api"]["spec"]["minAvailable"] == "50%"


def test_network_policy_requires_explicit_kube_api_server_cidrs():
    result = _run_helm({"networkPolicy": {"enabled": True}})

    assert result.returncode != 0
    assert "networkPolicy.kubeApiServer.cidrs" in result.stderr
    assert "wait-for-init" in result.stderr


def test_network_policy_renders_api_and_worker_policies_only():
    policies = _by_kind(_render(NETWORK_POLICY_ON), "NetworkPolicy")

    assert set(policies) == {"observal-api", "observal-worker"}
    assert policies["observal-api"]["spec"]["podSelector"]["matchLabels"] == _component("api")
    assert policies["observal-worker"]["spec"]["podSelector"]["matchLabels"] == _component("worker")


def test_api_policy_restricts_ingress_to_web_and_ingress_controller_on_app_port():
    api = _by_kind(_render(NETWORK_POLICY_ON), "NetworkPolicy")["observal-api"]
    spec = api["spec"]

    assert spec["policyTypes"] == ["Ingress"]
    assert len(spec["ingress"]) == 1
    rule = spec["ingress"][0]
    assert _ports(rule) == {("TCP", 8000)}
    assert _same_items(
        rule["from"],
        [
            {"podSelector": {"matchLabels": _component("web")}},
            {
                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}},
                "podSelector": {"matchLabels": {"app.kubernetes.io/name": "ingress-nginx"}},
            },
        ],
    )


def test_api_policy_omits_ingress_controller_peer_when_selectors_are_null():
    values = _merge(
        NETWORK_POLICY_ON,
        {"networkPolicy": {"ingressController": {"namespaceSelector": None, "podSelector": None}}},
    )
    api = _by_kind(_render(values), "NetworkPolicy")["observal-api"]

    # An empty peer would admit every pod in the namespace, so it must not render.
    assert [rule["from"] for rule in api["spec"]["ingress"]] == [[{"podSelector": {"matchLabels": _component("web")}}]]


def test_api_policy_includes_extra_ingress():
    extra = {"from": [{"ipBlock": {"cidr": "192.0.2.0/24"}}], "ports": [{"protocol": "TCP", "port": 8000}]}
    values = _merge(NETWORK_POLICY_ON, {"networkPolicy": {"api": {"extraIngress": [extra]}}})
    api = _by_kind(_render(values), "NetworkPolicy")["observal-api"]

    assert extra in api["spec"]["ingress"]


def test_worker_policy_denies_ingress_and_limits_egress_to_required_services():
    worker = _by_kind(_render(NETWORK_POLICY_ON), "NetworkPolicy")["observal-worker"]
    spec = worker["spec"]

    assert set(spec["policyTypes"]) == {"Ingress", "Egress"}
    assert not spec.get("ingress")
    assert all(rule.get("to") for rule in spec["egress"]), "no egress rule may be open to every destination"

    datastores = {
        (peer["podSelector"]["matchLabels"]["app.kubernetes.io/component"], port)
        for rule in spec["egress"]
        for peer in rule["to"]
        if "podSelector" in peer and "namespaceSelector" not in peer
        for _, port in _ports(rule)
    }
    assert datastores == {("db", 5432), ("clickhouse", 8123), ("redis", 6379)}
    for rule in spec["egress"]:
        for peer in rule["to"]:
            if "podSelector" in peer and "namespaceSelector" not in peer:
                assert SELECTOR.items() <= peer["podSelector"]["matchLabels"].items()

    dns = _dns_rules(worker)
    assert len(dns) == 1
    assert dns[0]["to"] == [
        {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        }
    ]

    api_server = [rule for rule in spec["egress"] if any("ipBlock" in peer for peer in rule["to"])]
    assert len(api_server) == 1
    assert api_server[0]["to"] == [{"ipBlock": {"cidr": API_SERVER_CIDR}}]
    assert _ports(api_server[0]) == {("TCP", 443), ("TCP", 6443)}


def test_worker_policy_datastore_peers_match_rendered_statefulsets():
    docs = _render(NETWORK_POLICY_ON)
    worker = _by_kind(docs, "NetworkPolicy")["observal-worker"]
    statefulsets = {
        sts["spec"]["template"]["metadata"]["labels"]["app.kubernetes.io/component"]: sts
        for sts in _by_kind(docs, "StatefulSet").values()
    }

    matched = set()
    for rule in worker["spec"]["egress"]:
        for peer in rule.get("to", []):
            if "podSelector" not in peer or "namespaceSelector" in peer:
                continue
            selector = peer["podSelector"]["matchLabels"]
            component = selector["app.kubernetes.io/component"]
            pod_template = statefulsets[component]["spec"]["template"]

            assert selector.items() <= pod_template["metadata"]["labels"].items()
            container_ports = {
                (port.get("protocol", "TCP"), port["containerPort"])
                for container in pod_template["spec"]["containers"]
                for port in container.get("ports", [])
            }
            assert _ports(rule) <= container_ports
            matched.add(component)

    assert matched == set(statefulsets) == {"db", "clickhouse", "redis"}


def test_worker_policy_dns_allows_any_destination_when_selectors_are_null():
    values = _merge(NETWORK_POLICY_ON, {"networkPolicy": {"dns": {"namespaceSelector": None, "podSelector": None}}})
    worker = _by_kind(_render(values), "NetworkPolicy")["observal-worker"]

    dns = _dns_rules(worker)
    assert len(dns) == 1
    assert "to" not in dns[0]


def test_worker_policy_omits_disabled_in_cluster_datastores():
    worker = _by_kind(_render(_merge(NETWORK_POLICY_ON, EXTERNAL_DATASTORES)), "NetworkPolicy")["observal-worker"]

    assert _egress_components(worker) == set()


@pytest.mark.parametrize(
    ("datastore", "component"), [("postgresql", "db"), ("clickhouse", "clickhouse"), ("redis", "redis")]
)
def test_worker_policy_omits_each_external_datastore(datastore, component):
    values = _merge(NETWORK_POLICY_ON, {datastore: EXTERNAL_DATASTORES[datastore]})
    worker = _by_kind(_render(values), "NetworkPolicy")["observal-worker"]

    assert _egress_components(worker) == {"db", "clickhouse", "redis"} - {component}


def test_worker_policy_includes_extra_egress():
    extra = {"to": [{"ipBlock": {"cidr": "203.0.113.10/32"}}], "ports": [{"protocol": "TCP", "port": 5432}]}
    values = _merge(NETWORK_POLICY_ON, EXTERNAL_DATASTORES, {"networkPolicy": {"worker": {"extraEgress": [extra]}}})
    worker = _by_kind(_render(values), "NetworkPolicy")["observal-worker"]

    assert extra in worker["spec"]["egress"]
