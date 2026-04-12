"""Secrets redactor for trace ingestion.

Strips API keys, tokens, passwords, and other secrets from trace data
BEFORE storage in ClickHouse.  Designed to avoid over-stripping:

    REDACTED:  OPENAI_KEY=sk-proj-abc123...   →  OPENAI_KEY=**REDACTED**
    KEPT:      $OPENAI_KEY                     →  $OPENAI_KEY  (reference)
    KEPT:      os.environ["OPENAI_KEY"]        →  unchanged   (code pattern)
    KEPT:      load_dotenv(".env")             →  unchanged   (file path)
"""

import re

# ---------------------------------------------------------------------------
# Known API key prefixes — near-zero false-positive rate.
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

_RE_JWT = re.compile(
    r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"
)

# ---------------------------------------------------------------------------
# PEM private keys
# ---------------------------------------------------------------------------

_RE_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ED25519 )?PRIVATE KEY-----"
    r"[\s\S]*?"
    r"-----END (?:RSA |EC |DSA |OPENSSH |ED25519 )?PRIVATE KEY-----"
)

# ---------------------------------------------------------------------------
# Key=value assignments where key name signals a secret.
# Matches:  API_KEY=abc123def  |  "password": "s3cret!"  |  token: sk-abc
# Skips:    $API_KEY  |  getenv("API_KEY")  |  API_KEY (no assignment)
# ---------------------------------------------------------------------------

_SECRET_KEY_NAMES = (
    r"(?:api[_\-]?key|api[_\-]?secret|secret[_\-]?key|auth[_\-]?token|"
    r"access[_\-]?token|private[_\-]?key|(?:db[_\-]?)?password|passwd|"
    r"(?:auth|api|access|refresh|bearer|session|jwt)[_\-]?token|"
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
    r"""["']?"""  # optional quotes around key name (JSON)
    + _SECRET_KEY_NAMES
    + r"""["']?\s*[=:]\s*"""
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
# This is the most aggressive pattern — kept last and narrow.
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

REDACTED = "**REDACTED**"


def redact_secrets(text: str) -> str:
    """Redact secrets from a string while preserving non-secret content.

    Safe to call on any string — returns the original if nothing matches.
    Idempotent: calling twice produces the same result.
    """
    if not text or len(text) < 8:
        return text

    # Already redacted — skip
    if text == REDACTED:
        return text

    # 1. PEM private keys (replace entire block)
    text = _RE_PRIVATE_KEY.sub(REDACTED, text)

    # 2. Known API key prefixes (highest confidence — always redact)
    for pat in _KNOWN_KEY_PATTERNS:
        text = pat.sub(REDACTED, text)

    # 3. JWT tokens
    text = _RE_JWT.sub(REDACTED, text)

    # 4. Key=value assignments with secret-sounding key names
    #    Replace only the VALUE, keep the key name
    def _replace_kv(m: re.Match) -> str:
        # Groups: 1=double-quoted, 2=single-quoted, 3=unquoted
        val = m.group(1) or m.group(2) or m.group(3)
        return m.group(0).replace(val, REDACTED) if val else m.group(0)

    text = _RE_KEY_VALUE.sub(_replace_kv, text)

    # 5. Connection strings — redact password only
    text = _RE_CONN_STRING.sub(r"\1" + REDACTED + r"\3", text)

    # 6. Auth headers — redact token only
    text = _RE_AUTH_HEADER.sub(r"\1" + REDACTED, text)

    return text


def redact_dict(data: dict, fields: set[str] | None = None) -> dict:
    """Redact secrets from specific string fields in a dict.

    If ``fields`` is None, redacts ALL string values.
    If ``fields`` is provided, only redacts those keys.
    Does NOT mutate the original — returns a new dict.
    """
    out = {}
    for key, value in data.items():
        if isinstance(value, str) and (fields is None or key in fields):
            out[key] = redact_secrets(value)
        elif isinstance(value, dict):
            out[key] = redact_dict(value, fields)
        else:
            out[key] = value
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
