#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Refresh vendored harness model catalogs."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "packages/observal-shared/observal_shared/harness_models"
PI_MODELS = "https://raw.githubusercontent.com/earendil-works/pi/main/packages/ai/src/models.generated.ts"
OPENCODE_ZEN = "https://opencode.ai/zen/v1/models"
TODAY = date.today().isoformat()


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Observal model refresher"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def write(name: str, models: list[dict], **extra: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = {"harness": name, "updated_at": TODAY, "models": models, **extra}
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def pi_models() -> tuple[list[dict], dict]:
    text = fetch(PI_MODELS)
    providers = re.findall(r'^\t"([^"]+)": \{', text, re.M)
    rows: list[dict] = []
    for provider in providers:
        start = text.find(f'\t"{provider}": {{')
        end = text.find('\n\t},', start)
        block = text[start:end]
        for mid, body in re.findall(r'\n\t\t"([^"]+)": \{(.*?)\n\t\t\}', block, re.S):
            label = re.search(r'\n\t\t\tname: "([^"]+)"', body)
            rows.append({
                "id": f"{provider}/{mid}",
                "label": label.group(1) if label else mid,
                "provider": provider,
                "kind": "exact",
            })
    rows += [
        {"id": "models-json:<provider>/<model-id>", "label": "Custom provider model from ~/.pi/agent/models.json", "provider": "custom", "kind": "provider_source"},
        {"id": "litellm:<model-id>", "label": "LiteLLM-discovered model", "provider": "litellm", "kind": "provider_source"},
    ]
    return rows, {"source": PI_MODELS, "provider_count": len(providers)}


def opencode_models() -> list[dict]:
    raw = fetch(OPENCODE_ZEN)
    payload = raw[raw.find('{'):]
    data = json.loads(payload)
    rows = [
        {"id": f"opencode/{m['id']}", "label": m["id"], "provider": "opencode", "kind": "exact"}
        for m in data.get("data", [])
    ]
    rows.append({"id": "<provider>/<model-id>", "label": "Configured OpenCode provider model", "provider": "custom", "kind": "provider_source"})
    return rows


STATIC: dict[str, list[dict]] = {
    "cursor": [
        {"id": x, "label": x, "provider": "cursor", "kind": "exact"} for x in [
            "auto", "composer-2.5", "composer-2", "gpt-5.5", "gpt-5.5-fast", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.3-codex", "gpt-5.3-codex-high", "claude-fable-5", "claude-opus-4-8", "claude-opus-4-8-fast", "claude-sonnet-4-6", "gemini-3.5-flash", "gemini-3.1-pro", "gemini-3-flash", "grok-build-0.1", "inherit",
        ]
    ],
    "kiro": [
        {"id": x, "label": x, "provider": "kiro", "kind": "exact"} for x in [
            "auto", "claude-sonnet-4", "claude-sonnet-4-5", "claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-5", "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8", "minimax-m2.5", "minimax-m2.1", "glm-5", "deepseek-3.2", "qwen3-coder-next",
        ]
    ],
    "claude-code": [
        {"id": x, "label": x, "provider": "anthropic", "kind": "alias" if x in {"default","best","fable","opus","sonnet","haiku","opusplan","inherit","sonnet[1m]","opus[1m]","opusplan[1m]"} else "exact"} for x in [
            "default", "best", "fable", "opus", "sonnet", "haiku", "opusplan", "inherit", "sonnet[1m]", "opus[1m]", "opusplan[1m]", "claude-fable-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6", "claude-sonnet-4-5", "claude-haiku-4-5",
        ]
    ],
    "codex": [
        {"id": x, "label": x, "provider": "openai", "kind": "exact"} for x in ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.3-codex", "gpt-5.3-codex-spark", "gpt-5.2", "gpt-5.2-codex", "gpt-5.1", "gpt-5.1-codex", "gpt-5.1-codex-max", "gpt-5.1-codex-mini"]
    ] + [
        {"id": "model_providers.<id>:<model>", "label": "Custom Codex model provider", "provider": "custom", "kind": "provider_source"},
        {"id": "amazon-bedrock:<bedrock-model-id>", "label": "Amazon Bedrock model", "provider": "amazon-bedrock", "kind": "provider_source"},
        {"id": "ollama:<model>", "label": "Ollama model", "provider": "ollama", "kind": "provider_source"},
        {"id": "lmstudio:<model>", "label": "LM Studio model", "provider": "lmstudio", "kind": "provider_source"},
    ],
    "copilot": [
        {"id": x, "label": x, "provider": "github", "kind": "exact"} for x in ["auto", "claude-sonnet-4.5", "claude-opus-4.7", "claude-haiku-4.5", "gemini-3.1-pro", "gemini-3.5-flash", "gpt-5.4-mini"]
    ],
    "copilot-cli": [
        {"id": "auto", "label": "Auto", "provider": "github", "kind": "exact"},
        {"id": "COPILOT_PROVIDER_TYPE=openai;COPILOT_MODEL=<model>", "label": "OpenAI-compatible BYOK model", "provider": "openai", "kind": "provider_source"},
        {"id": "COPILOT_PROVIDER_TYPE=azure;COPILOT_MODEL=<deployment>", "label": "Azure OpenAI deployment", "provider": "azure", "kind": "provider_source"},
        {"id": "COPILOT_PROVIDER_TYPE=anthropic;COPILOT_MODEL=<claude-model>", "label": "Anthropic BYOK model", "provider": "anthropic", "kind": "provider_source"},
    ],
    "antigravity": [
        {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash", "provider": "google", "kind": "exact", "efforts": ["low", "medium", "high"]},
        {"id": "gemini-3.1-pro", "label": "Gemini 3.1 Pro", "provider": "google", "kind": "exact", "efforts": ["low", "high"]},
        {"id": "gemini-3-flash", "label": "Gemini 3 Flash", "provider": "google", "kind": "exact"},
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "provider": "anthropic", "kind": "exact", "efforts": ["thinking"]},
        {"id": "claude-opus-4-6", "label": "Claude Opus 4.6", "provider": "anthropic", "kind": "exact", "efforts": ["thinking"]},
        {"id": "gpt-oss-120b-maas", "label": "GPT-OSS 120B", "provider": "openai", "kind": "exact", "efforts": ["medium"]},
        {"id": "antigravity-preview-05-2026", "label": "Antigravity Agent API", "provider": "google", "kind": "exact"},
        {"id": "gemini-enterprise:<model-id>", "label": "Gemini Enterprise Agent Platform model", "provider": "google-cloud", "kind": "provider_source"},
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, models in STATIC.items():
        write(name, models)
    pi, meta = pi_models()
    write("pi", pi, **meta)
    write("opencode", opencode_models(), source=OPENCODE_ZEN)
    if args.check:
        pi_data = json.loads((OUT / "pi.json").read_text())
        oc_data = json.loads((OUT / "opencode.json").read_text())
        ag_data = json.loads((OUT / "antigravity.json").read_text())
        assert pi_data["provider_count"] >= 30 and len(pi_data["models"]) >= 900
        assert any(m["id"].startswith("opencode/") for m in oc_data["models"])
        assert any(m["id"] == "gemini-enterprise:<model-id>" for m in ag_data["models"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
