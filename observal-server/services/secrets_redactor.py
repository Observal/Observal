# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 tsitu0 <tomsitu0102@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Secrets redactor for trace ingestion.

Strips API keys, tokens, passwords, and other secrets from trace data
BEFORE storage in ClickHouse.  Designed to avoid over-stripping:

    REDACTED:  OPENAI_KEY=sk-proj-abc123...   →  OPENAI_KEY=**REDACTED**
    KEPT:      $OPENAI_KEY                     →  $OPENAI_KEY  (reference)
    KEPT:      os.environ["OPENAI_KEY"]        →  unchanged   (code pattern)
    KEPT:      load_dotenv(".env")             →  unchanged   (file path)
"""

import re
from typing import Any

from loguru import logger as optic

# ---------------------------------------------------------------------------
# Known API key prefixes - near-zero false-positive rate.
# These match actual key VALUES, not variable names.
# ---------------------------------------------------------------------------

_KNOWN_KEY_PATTERNS: list[re.Pattern] = [
    # OpenAI
    re.compile(r"sk-(?:proj-)?[a-zA-Z0-9\-_]{20,}"),
    # Anthropic
    re.compile(r"sk-ant-[a-zA-Z0-9\-_]{20,}"),
    # Stripe
    re.compile(r"[prs]k_(?:live|test)_[a-zA-Z0-9]{20,}"),
    # GitHub tokens
    re.compile(r"gh[pousr]_[a-zA-Z0-9]{36,}"),
    # GitLab PAT
    re.compile(r"glpat-[a-zA-Z0-9\-_]{20,}"),
    # Slack tokens
    re.compile(r"xox[bpsa]-[a-zA-Z0-9\-]{10,}"),
    # AWS access key ID
    re.compile(r"AKIA[A-Z0-9]{16}"),
    # AWS secret key (40 char base64-ish after an = or : delimiter)
    re.compile(r"(?<=[\=:\s\"\'])[a-zA-Z0-9/+]{40}(?=[\"\';\s,}]|$)"),
    # npm token
    re.compile(r"npm_[a-zA-Z0-9]{36,}"),
    # PyPI token
    re.compile(r"pypi-[a-zA-Z0-9]{50,}"),
    # SendGrid
    re.compile(r"SG\.[a-zA-Z0-9\-_]{22,}\.[a-zA-Z0-9\-_]{22,}"),
    # Twilio
    re.compile(r"SK[a-f0-9]{32}"),
    # Mailgun
    re.compile(r"key-[a-zA-Z0-9]{32}"),
    # HuggingFace
    re.compile(r"hf_[a-zA-Z0-9]{34,}"),
    # Vercel
    re.compile(r"vercel_[a-zA-Z0-9\-_]{24,}"),
    # Supabase
    re.compile(r"sbp_[a-zA-Z0-9]{40,}"),
    # age encryption key
    re.compile(r"AGE-SECRET-KEY-[A-Z0-9]{59}"),
    # Google AI / Gemini
    re.compile(r"AIza[a-zA-Z0-9\-_]{35}"),
]

# ---------------------------------------------------------------------------
# JWT tokens (three base64url segments separated by dots)
# ---------------------------------------------------------------------------

_RE_JWT = re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}")

# ---------------------------------------------------------------------------
# PEM private keys
# ---------------------------------------------------------------------------

_RE_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"[^-]+"
    r"-----END [A-Z ]*PRIVATE KEY-----"
)

# ---------------------------------------------------------------------------
# Key=value assignments where key name signals a secret.
# Matches:  API_KEY=abc123def  |  "password": "s3cret!"  |  token: sk-abc
# Skips:    $API_KEY  |  getenv("API_KEY")  |  API_KEY (no assignment)
# ---------------------------------------------------------------------------

_SECRET_KEY_NAMES = (
    r"(?:api[_\-]?key|api[_\-]?secret|secret[_\-]?key|auth[_\-]?token|"
    r"access[_\-]?token|private[_\-]?key|(?:db[_\-]?)?password|passwd|"
    r"(?:auth|api|access|refresh|bearer|session|jwt)[_\-]?token|token|"
    r"client[_\-]?secret|signing[_\-]?key|encryption[_\-]?key|"
    r"db[_\-]?password|redis[_\-]?password|database[_\-]?password|"
    r"webhook[_\-]?secret|secret|credentials?)"
)

# key = "value" or key: "value" or KEY=value  (value must be 8+ chars)
# Two alternatives: quoted values (capture content between quotes) or unquoted
# Key name may be quoted in JSON: "password": "value"
_RE_KEY_VALUE = re.compile(
    r"(?i)"
    r"(?<!\$)(?<!\$\{)"  # NOT preceded by $ or ${  (env var reference)
    r"""["']?""" + _SECRET_KEY_NAMES + r"""["']?\s*[=:]\s*"""  # optional quotes around key name (JSON)
    r"(?:"
    r'"([^"\n]{8,})"'  # double-quoted value
    r"|'([^'\n]{8,})'"  # single-quoted value
    r"|([^\s\"'\n,;}{]{8,})"  # unquoted value
    r")",
)

# ---------------------------------------------------------------------------
# Connection strings with embedded passwords
# postgresql://user:PASSWORD@host/db  |  mongodb+srv://u:P@host
# ---------------------------------------------------------------------------

_RE_CONN_STRING = re.compile(
    r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis(?:s)?|amqps?|mssql)"
    r"://[^:]+:)"
    r"([^@\s]{4,})"  # the password
    r"(@)",
)

# ---------------------------------------------------------------------------
# Authorization headers in text
# Authorization: Bearer <token>  |  X-API-Key: abc123
# ---------------------------------------------------------------------------

_RE_AUTH_HEADER = re.compile(
    r"(?i)"
    r"((?:Authorization|X-API-Key|X-Auth-Token)\s*:\s*(?:Bearer\s+)?)"
    r"([a-zA-Z0-9+/=\-_.]{16,})"
)

# ---------------------------------------------------------------------------
# Generic high-entropy hex/base64 strings that look like secrets.
# Only matches 32+ char strings that contain mixed case/digits,
# and only when preceded by an assignment operator (=, :).
# This is the most aggressive pattern - kept last and narrow.
# ---------------------------------------------------------------------------

_RE_LONG_HEX = re.compile(
    r"(?<=[=:\s])"
    r"([A-Fa-f0-9]{32,})"
    r"(?=[\s\"',;}\])]|$)"
)

_RE_LONG_BASE64 = re.compile(
    r"(?<=[=:\s\"'])"
    r"([A-Za-z0-9+/]{40,}={0,2})"
    r"(?=[\"',;\s}\])]|$)"
)

# Combined alternation of all known key patterns for single-pass matching.
# A single DFA scan is dramatically faster than 15 sequential subn() calls.
_COMBINED_KEY_PATTERN = re.compile("|".join(f"(?:{p.pattern})" for p in _KNOWN_KEY_PATTERNS))

# Quick substring prefixes for short-circuit: if none are present in the text,
# no known API key can exist, so skip the expensive combined regex entirely.
_QUICK_PREFIXES = (
    "sk-",
    "sk_",
    "pk_",
    "rk_",
    "ghp_",
    "gho_",
    "ghs_",
    "ghu_",
    "glpat-",
    "xox",
    "AKIA",
    "npm_",
    "pypi-",
    "SG.",
    "hf_",
    "vercel_",
    "sbp_",
    "AGE-SECRET",
    "AIza",
    "key-",
)

REDACTED = "**REDACTED**"

_redaction_count: int = 0


def get_and_reset_redaction_count() -> int:
    global _redaction_count
    count = _redaction_count
    _redaction_count = 0
    return count


def redact_secrets(text: str) -> str:
    """Redact secrets from a string while preserving non-secret content.

    Safe to call on any string - returns the original if nothing matches.
    Idempotent: calling twice produces the same result.
    """
    optic.trace("redacting secrets from {} chars of text", len(text) if text else 0)
    if not text or len(text) < 8:
        return text

    # Already redacted - skip
    if text == REDACTED:
        return text

    # 1. PEM private keys (replace entire block)
    text = _RE_PRIVATE_KEY.sub(REDACTED, text)

    # 2. Known API key prefixes (single-pass alternation with short-circuit)
    global _redaction_count
    if any(prefix in text for prefix in _QUICK_PREFIXES):
        text, n = _COMBINED_KEY_PATTERN.subn(REDACTED, text)
        _redaction_count += n

    # 3. JWT tokens
    text = _RE_JWT.sub(REDACTED, text)

    # 4. Key=value assignments with secret-sounding key names
    #    Replace only the VALUE, keep the key name
    def _replace_kv(m: re.Match) -> str:
        optic.trace("redacted a secret match")
        # Groups: 1=double-quoted, 2=single-quoted, 3=unquoted
        val = m.group(1) or m.group(2) or m.group(3)
        return m.group(0).replace(val, REDACTED) if val else m.group(0)

    text = _RE_KEY_VALUE.sub(_replace_kv, text)

    # 5. Connection strings - redact password only
    text = _RE_CONN_STRING.sub(r"\1" + REDACTED + r"\3", text)

    # 6. Auth headers - redact token only
    text = _RE_AUTH_HEADER.sub(r"\1" + REDACTED, text)

    return text


# Dict keys whose VALUE should be redacted wholesale based on the key name alone.
# Pattern redaction only catches secrets that look like secrets (key=value text,
# known prefixes, JWTs, ...); a structured payload such as {"api_key": "plainval"}
# carries the secret as a bare value the patterns never match. This matcher closes
# that gap. It is deliberately narrower than _SECRET_KEY_NAMES -- it excludes the
# bare "token"/"secret"/"credentials" alternatives so metric keys like
# "token_count" or "max_tokens" are not redacted.
_RE_SECRET_KEY_NAME = re.compile(
    r"(?i)^(?:[a-z0-9]+[_\-.])*"
    r"(?:api[_\-]?key|api[_\-]?secret|secret[_\-]?key|"
    r"(?:auth|access|refresh|bearer|session|jwt)[_\-]?token|"
    r"private[_\-]?key|signing[_\-]?key|encryption[_\-]?key|"
    r"client[_\-]?secret|webhook[_\-]?secret|"
    r"(?:db[_\-]?|redis[_\-]?|database[_\-]?)?passw(?:or)?d|"
    r"credentials?)$"
)


def _looks_like_secret_key(key: Any) -> bool:
    """True if a dict key name signals that its value is a secret.

    Handles snake_case, kebab-case, dotted, and camelCase keys (``apiKey`` is
    normalized to ``api_key``). Used to redact structured values where the secret
    is the value rather than embedded as ``key=value`` text.
    """
    if not isinstance(key, str):
        return False
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return bool(_RE_SECRET_KEY_NAME.match(normalized))


def _redact_value(value: Any) -> Any:
    """Recursively redact all string values in a structured value.

    Two redaction signals are applied: (1) any dict value whose KEY name signals a
    secret is replaced wholesale, and (2) every string value is run through the
    pattern-based redactor.
    """
    optic.trace("redacting value field")
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {
            k: (REDACTED if (_looks_like_secret_key(k) and v is not None) else _redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def redact_value(value: Any) -> Any:
    """Recursively redact string values from dict/list/scalar payloads.

    Public wrapper for ingestion code that needs to sanitize a whole structured
    value before storage. Does not mutate the original object.
    """
    return _redact_value(value)


def _redact_matching_fields(value: Any, fields: set[str]) -> Any:
    """Recurse through containers looking for dict keys selected by fields."""
    optic.trace("redacting {} specified fields", len(fields))
    if isinstance(value, dict):
        return redact_dict(value, fields)
    if isinstance(value, list):
        return [_redact_matching_fields(item, fields) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_matching_fields(item, fields) for item in value)
    return value


def redact_dict(data: dict, fields: set[str] | None = None) -> dict:
    """Redact secrets from specific fields in a dict.

    If ``fields`` is None, redacts ALL string values recursively.
    If ``fields`` is provided, redacts complete values under those keys,
    including nested dicts/lists.
    Does NOT mutate the original - returns a new dict.
    """
    optic.trace("redacting fields from data structure")
    out = {}
    for key, value in data.items():
        if fields is None or key in fields:
            out[key] = _redact_value(value)
        else:
            out[key] = _redact_matching_fields(value, fields)
    return out


# Fields that commonly carry user content and could contain secrets.
# Used by ingestion endpoints to know which attrs to redact.
INGESTION_FIELDS = {
    "tool_input",
    "tool_response",
    "error",
    "input",
    "output",
    "gen_ai.prompt",
    "gen_ai.completion",
    "input_params",
    "response",
    "comment",
    "prompt",
    "assistant_response",
    "user_prompt",
    "last_assistant_message",
    "summary",
    "message",
}
