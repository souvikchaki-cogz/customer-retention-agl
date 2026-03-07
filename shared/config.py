"""
Centralised configuration for the AGL Energy Customer Churn Retention System.
All environment variables are read once at import time from os.environ / .env.
"""

import os

def _get_float(var: str, default: str) -> float:
    try:
        return float(os.getenv(var, default))
    except Exception:
        return float(default)

def _get_int(var: str, default: str) -> int:
    try:
        return int(os.getenv(var, default))
    except Exception:
        return int(default)

# ── Scoring thresholds ────────────────────────────────────────────────────────
LEAD_SCORE_THRESHOLD = _get_float("LEAD_SCORE_THRESHOLD", "0.60")
CONFIDENCE_FLOOR = _get_float("CONFIDENCE_FLOOR", "0.55")
EVIDENCE_MIN_LEN = _get_int("EVIDENCE_MIN_LEN", "4")

# ── Azure SQL Database ────────────────────────────────────────────────────────
AZSQL_SERVER    = os.getenv("AZSQL_SERVER",    "")
AZSQL_DB        = os.getenv("AZSQL_DB",        "")
AZSQL_UID       = os.getenv("AZSQL_UID",       "")
AZSQL_PWD       = os.getenv("AZSQL_PWD",       "")
AZSQL_DRIVER    = os.getenv("AZSQL_DRIVER",    "{ODBC Driver 18 for SQL Server}")
MANAGED_IDENTITY_CLIENT_ID = os.getenv("MANAGED_IDENTITY_CLIENT_ID", "")

# ── Azure OpenAI ──────────────────────────────────────────────────────────────
AZURE_OPENAI_API_ENDPOINT   = os.getenv("AZURE_OPENAI_API_ENDPOINT",   "")
AZURE_OPENAI_API_KEY        = os.getenv("AZURE_OPENAI_API_KEY",        "")
AZURE_OPENAI_DEPLOYMENTNAME = os.getenv("AZURE_OPENAI_DEPLOYMENTNAME", "")

AZURE_OPENAI_API_VERSION    = os.getenv("AZURE_OPENAI_API_VERSION",    "2025-01-01-preview")

# ── Azure Functions ───────────────────────────────────────────────────────────
FUNCTION_START_URL  = os.getenv("FUNCTION_START_URL", "")
FUNCTION_BASE_URL   = os.getenv("FUNCTION_BASE_URL",  "http://localhost:7071")
FUNCTION_CODE       = os.getenv("FUNCTION_CODE",      "")

# ── Application ───────────────────────────────────────────────────────────────
LOG_LEVEL           = os.getenv("LOG_LEVEL",           "INFO")
REPLAY_QUEUE_NAME   = os.getenv("REPLAY_QUEUE_NAME",   "event-replay")
USE_SQL_RULES       = os.getenv("USE_SQL_RULES",       "1")
AGENT_VERSION       = os.getenv("AGENT_VERSION",       "1.0.0")

# ── Standardized paths ─────────────────────────────────────────────────────────────
# Path to the default local ruleset YAML for fallback loading; can be overridden via env
DEFAULT_RULESET_YAML_PATH = os.getenv(
    "DEFAULT_RULESET_YAML_PATH",
    os.path.join(os.path.dirname(__file__), "..", "sample_rules.yaml")
)