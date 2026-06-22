# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Refresh the vendored LiteLLM model catalog snapshot."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
OUT_PATH = Path(__file__).resolve().parents[1] / "observal-server" / "data" / "litellm_model_catalog.json"
CAPABILITY_FLAGS = (
    "supports_function_calling",
    "supports_tool_choice",
    "supports_parallel_function_calling",
    "supports_response_schema",
    "supports_native_structured_output",
    "supports_vision",
    "supports_pdf_input",
    "supports_audio_input",
    "supports_audio_output",
    "supports_video_input",
    "supports_prompt_caching",
    "supports_reasoning",
    "supports_web_search",
    "supports_computer_use",
    "supports_system_messages",
)


def litellm_provider(provider: str) -> str:
    return "bedrock" if provider == "bedrock_converse" else provider


def litellm_model(model_id: str, provider: str) -> str:
    if provider == "bedrock_converse":
        return f"bedrock/converse/{model_id}"
    return model_id if model_id.startswith(f"{provider}/") else f"{provider}/{model_id}"


def normalize(payload: dict) -> dict:
    models = []
    for model_id, row in payload.items():
        if model_id == "sample_spec" or not isinstance(row, dict):
            continue
        source_provider = row.get("litellm_provider")
        if not source_provider:
            continue
        provider = litellm_provider(source_provider)
        models.append(
            {
                "model_id": model_id,
                "litellm_provider": provider,
                "litellm_model": litellm_model(model_id, source_provider),
                "mode": row.get("mode") or "",
                "max_input_tokens": row.get("max_input_tokens"),
                "max_output_tokens": row.get("max_output_tokens") or row.get("max_tokens"),
                "input_cost_per_token": row.get("input_cost_per_token"),
                "output_cost_per_token": row.get("output_cost_per_token"),
                "deprecation_date": row.get("deprecation_date"),
                "deprecated": bool(row.get("deprecation_date")),
                "capabilities": [flag.removeprefix("supports_") for flag in CAPABILITY_FLAGS if row.get(flag)],
            }
        )

    models.sort(key=lambda item: (item["litellm_provider"], item["model_id"]))
    return {
        "source": SOURCE_URL,
        "fetched_at": datetime.now(UTC).isoformat(),
        "model_count": len(models),
        "chat_model_count": sum(1 for model in models if model["mode"] == "chat"),
        "models": models,
    }


def main() -> None:
    request = Request(SOURCE_URL, headers={"User-Agent": "observal/1.0"})
    with urlopen(request, timeout=30) as response:
        snapshot = normalize(json.load(response))

    assert snapshot["model_count"] > 0
    assert snapshot["chat_model_count"] > 0
    assert all("/" in model["litellm_model"] for model in snapshot["models"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {snapshot['model_count']} models ({snapshot['chat_model_count']} chat) to {OUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"failed to refresh LiteLLM model snapshot: {exc}", file=sys.stderr)
        raise
