"""Tests for the secrets redactor — verifies redaction accuracy and no over-stripping."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "observal-server"))

from services.secrets_redactor import REDACTED, redact_dict, redact_secrets

# ============================================================================
# Known API key prefixes — MUST be redacted
# ============================================================================


class TestKnownKeyPrefixes:
    def test_openai_key(self):
        text = "Using OPENAI_KEY=sk-proj-abc123def456ghi789jkl012mno345"
        result = redact_secrets(text)
        assert "sk-proj-" not in result
        assert REDACTED in result
        assert "OPENAI_KEY=" in result  # key name preserved

    def test_openai_classic_key(self):
        assert REDACTED in redact_secrets("sk-abcdefghijklmnopqrstuvwxyz1234567890")

    def test_anthropic_key(self):
        assert REDACTED in redact_secrets("sk-ant-api03-abcdefghijklmnopqrstuvwxyz")

    def test_stripe_secret(self):
        # Use obviously fake key (repeating chars) to avoid GitHub push protection
        assert REDACTED in redact_secrets("sk_live_FAKEFAKEFAKEFAKEFAKE00")

    def test_stripe_publishable(self):
        assert REDACTED in redact_secrets("pk_test_FAKEFAKEFAKEFAKEFAKE00")

    def test_github_pat(self):
        assert REDACTED in redact_secrets("ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd")

    def test_github_oauth(self):
        assert REDACTED in redact_secrets("gho_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd")

    def test_gitlab_pat(self):
        assert REDACTED in redact_secrets("glpat-abcDEFghiJKLmnoPQRstuv")

    def test_slack_bot_token(self):
        assert REDACTED in redact_secrets("xoxb-123456789-abcdefghij")

    def test_aws_access_key(self):
        assert REDACTED in redact_secrets("AKIAIOSFODNN7EXAMPLE")

    def test_npm_token(self):
        assert REDACTED in redact_secrets("npm_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd")

    def test_huggingface_token(self):
        assert REDACTED in redact_secrets("hf_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890")

    def test_sendgrid_key(self):
        assert REDACTED in redact_secrets("SG.abcDEFghiJKLmnoPQRstuv.wxyzABCDEFghiJKLmnoPQRstuv")

    def test_google_ai_key(self):
        assert REDACTED in redact_secrets("AIzaSyA-abcdefghijklmnopqrstuvwxyz12345")


# ============================================================================
# JWT tokens — MUST be redacted
# ============================================================================


class TestJWT:
    def test_jwt_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        result = redact_secrets(jwt)
        assert "eyJ" not in result
        assert REDACTED in result


# ============================================================================
# PEM private keys — MUST be redacted
# ============================================================================


class TestPrivateKeys:
    def test_rsa_private_key(self):
        pem = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF8PbnGcY5unA67hgYGPV1k1YBm
IICAQEA0Z3VS5JJcds3xfn/ygWyF8PbnGcY5unA67hgYGPV1k1YBm
-----END RSA PRIVATE KEY-----"""
        result = redact_secrets(pem)
        assert "MIIEpA" not in result
        assert REDACTED in result

    def test_ec_private_key(self):
        pem = "-----BEGIN EC PRIVATE KEY-----\nfakedata\n-----END EC PRIVATE KEY-----"
        assert REDACTED in redact_secrets(pem)


# ============================================================================
# Key=value assignments — MUST redact the VALUE, keep the key name
# ============================================================================


class TestKeyValueAssignments:
    def test_api_key_equals(self):
        text = "OPENAI_API_KEY=12497612946917xeeihrEUT="
        result = redact_secrets(text)
        assert "12497612946917" not in result
        assert REDACTED in result

    def test_json_password(self):
        text = '{"password": "mySuperSecretPassword123!"}'
        result = redact_secrets(text)
        assert "mySuperSecretPassword123" not in result
        assert REDACTED in result

    def test_yaml_secret(self):
        text = "client_secret: abcdef1234567890abcdef"
        result = redact_secrets(text)
        assert "abcdef1234567890" not in result

    def test_auth_token_colon(self):
        text = "auth_token: my-long-secret-token-value-here"
        result = redact_secrets(text)
        assert "my-long-secret-token-value-here" not in result

    def test_db_password(self):
        text = "DB_PASSWORD=hunter2_but_longer_this_time"
        result = redact_secrets(text)
        assert "hunter2_but_longer" not in result


# ============================================================================
# Connection strings — MUST redact the password only
# ============================================================================


class TestConnectionStrings:
    def test_postgres(self):
        text = "postgresql://admin:s3cretP@ss@localhost:5432/mydb"
        result = redact_secrets(text)
        assert "s3cretP@ss" not in result
        assert "postgresql://admin:" in result
        assert "@localhost:5432/mydb" in result

    def test_mongodb(self):
        text = "mongodb+srv://user:longpassword123@cluster.mongodb.net/db"
        result = redact_secrets(text)
        assert "longpassword123" not in result
        assert "mongodb+srv://user:" in result

    def test_redis(self):
        text = "redis://default:myRedisPass@redis.host:6379"
        result = redact_secrets(text)
        assert "myRedisPass" not in result


# ============================================================================
# Authorization headers — MUST redact the token
# ============================================================================


class TestAuthHeaders:
    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abc123"
        result = redact_secrets(text)
        assert "eyJhbGci" not in result

    def test_x_api_key_header(self):
        text = "X-API-Key: abcdef1234567890abcdef1234567890"
        result = redact_secrets(text)
        assert "abcdef1234567890" not in result
        assert "X-API-Key:" in result


# ============================================================================
# Things that must NOT be stripped (over-stripping prevention)
# ============================================================================


class TestNoOverStripping:
    def test_env_var_reference_dollar(self):
        """$OPENAI_KEY should NOT be redacted — it's a reference, not a value."""
        text = "export PATH=$OPENAI_KEY:$PATH"
        assert text == redact_secrets(text)

    def test_env_var_reference_dollar_brace(self):
        """${SECRET_KEY} should NOT be redacted."""
        text = 'value = "${SECRET_KEY}"'
        assert text == redact_secrets(text)

    def test_python_getenv(self):
        """os.environ['KEY'] or os.getenv('KEY') — code pattern, not a secret."""
        text = 'key = os.environ["OPENAI_API_KEY"]'
        assert text == redact_secrets(text)

    def test_dotenv_path(self):
        """File path reference to .env file."""
        text = 'load_dotenv(".env")'
        assert text == redact_secrets(text)

    def test_key_name_alone(self):
        """Just the key name without a value assignment."""
        text = "Make sure you set OPENAI_API_KEY"
        assert text == redact_secrets(text)

    def test_short_values(self):
        """Very short values should NOT be redacted (likely test/dummy data)."""
        text = "password=abc"
        # 3 chars is below our 8-char threshold
        assert text == redact_secrets(text)

    def test_normal_code(self):
        """Regular code should pass through untouched."""
        text = "def calculate_sum(a, b):\n    return a + b"
        assert text == redact_secrets(text)

    def test_normal_prose(self):
        """Normal English text should not be mangled."""
        text = "The API key is stored securely and rotated every 90 days."
        assert text == redact_secrets(text)

    def test_file_paths(self):
        """File paths should not be redacted."""
        text = "/etc/ssl/certs/ca-certificates.crt"
        assert text == redact_secrets(text)

    def test_urls_without_passwords(self):
        """URLs without embedded passwords should not be touched."""
        text = "https://api.example.com/v1/users?limit=100"
        assert text == redact_secrets(text)

    def test_empty_and_short_strings(self):
        assert redact_secrets("") == ""
        assert redact_secrets("hi") == "hi"
        assert redact_secrets(None) is None  # type: ignore[arg-type]

    def test_already_redacted(self):
        assert redact_secrets(REDACTED) == REDACTED

    def test_hex_color_not_redacted(self):
        """Hex color codes are short enough to not trigger."""
        text = "color: #ff5733;"
        assert text == redact_secrets(text)

    def test_git_sha_in_normal_context(self):
        """Git SHAs in normal context should be left alone."""
        text = "commit abc123def456"
        assert text == redact_secrets(text)


# ============================================================================
# Mixed content — realistic trace payloads
# ============================================================================


class TestRealisticTraces:
    def test_tool_input_with_env_file_content(self):
        """A Read tool reading a .env file — values should be redacted."""
        text = (
            "File contents of .env:\n"
            "OPENAI_API_KEY=sk-proj-abc123def456ghi789jkl012mno345\n"
            "DATABASE_URL=postgresql://admin:s3cret@localhost:5432/app\n"
            "DEBUG=true\n"
            "PORT=8080"
        )
        result = redact_secrets(text)
        assert "sk-proj-" not in result
        assert "s3cret" not in result
        assert "DEBUG=true" in result  # non-secret preserved
        assert "PORT=8080" in result  # non-secret preserved

    def test_tool_output_with_code(self):
        """Tool output showing code that references env vars — don't strip."""
        text = 'import os\nkey = os.environ["OPENAI_API_KEY"]\nclient = OpenAI(api_key=key)\n'
        result = redact_secrets(text)
        assert 'os.environ["OPENAI_API_KEY"]' in result

    def test_error_message_with_leaked_key(self):
        """Error message accidentally containing a key."""
        text = "AuthenticationError: Invalid API key: sk-proj-abc123def456ghi789jkl012mno345"
        result = redact_secrets(text)
        assert "sk-proj-" not in result
        assert "AuthenticationError" in result


# ============================================================================
# redact_dict helper
# ============================================================================


class TestRedactDict:
    def test_redacts_specified_fields(self):
        data = {
            "tool_name": "Read",
            "tool_input": "api_key=sk-proj-abc123def456ghi789jkl012mno345",
            "session_id": "abc123",
        }
        result = redact_dict(data, fields={"tool_input", "tool_response"})
        assert "sk-proj-" not in result["tool_input"]
        assert result["tool_name"] == "Read"
        assert result["session_id"] == "abc123"

    def test_skips_unspecified_fields(self):
        data = {
            "tool_name": "sk-proj-abc123def456ghi789jkl012mno345",  # key in wrong field
            "tool_input": "normal text",
        }
        result = redact_dict(data, fields={"tool_input"})
        # tool_name is NOT in the fields set, so the key leaks (by design)
        assert "sk-proj-" in result["tool_name"]
        assert result["tool_input"] == "normal text"

    def test_redacts_all_fields_when_none(self):
        data = {
            "a": "sk-proj-abc123def456ghi789jkl012mno345",
            "b": "normal",
        }
        result = redact_dict(data, fields=None)
        assert "sk-proj-" not in result["a"]
        assert result["b"] == "normal"


# ============================================================================
# Idempotency
# ============================================================================


class TestIdempotency:
    def test_double_redact(self):
        text = "OPENAI_KEY=sk-proj-abc123def456ghi789jkl012mno345"
        once = redact_secrets(text)
        twice = redact_secrets(once)
        assert once == twice
