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
# Energy retailer switching in Australia is low-friction and government-promoted
# (Energy Made Easy), so churn happens faster than mortgage refinancing.
# Thresholds are set slightly lower than the original banking values to catch
# earlier-stage signals before the customer has already decided to leave.

LEAD_SCORE_THRESHOLD = _get_float("LEAD_SCORE_THRESHOLD", "0.60")  # Lowered from 0.7 — energy switching is low-friction
CONFIDENCE_FLOOR = _get_float("CONFIDENCE_FLOOR", "0.55")          # Slightly lower — energy NLP is more conversational
EVIDENCE_MIN_LEN = _get_int("EVIDENCE_MIN_LEN", "4")


# ── Azure SQL Database ────────────────────────────────────────────────────────
AZSQL_SERVER    = os.getenv("AZSQL_SERVER",    "")
AZSQL_DB        = os.getenv("AZSQL_DB",        "")
AZSQL_DRIVER    = os.getenv("AZSQL_DRIVER",    "{ODBC Driver 18 for SQL Server}")


# ── Azure OpenAI ──────────────────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT       = os.getenv("AZURE_OPENAI_ENDPOINT",       "")
AZURE_OPENAI_API_KEY        = os.getenv("AZURE_OPENAI_API_KEY",        "")
AZURE_OPENAI_DEPLOYMENT     = os.getenv("AZURE_OPENAI_DEPLOYMENT",     "")
AZURE_OPENAI_API_VERSION    = os.getenv("AZURE_OPENAI_API_VERSION",    "2025-01-01-preview")


# ── Azure Functions ───────────────────────────────────────────────────────────
FUNCTION_START_URL = os.getenv("FUNCTION_START_URL", "")
FUNCTION_BASE_URL  = os.getenv("FUNCTION_BASE_URL",  "http://localhost:7071")
FUNCTION_CODE      = os.getenv("FUNCTION_CODE",      "")


# ── Application ───────────────────────────────────────────────────────────────
LOG_LEVEL           = os.getenv("LOG_LEVEL",           "INFO")
REPLAY_QUEUE_NAME   = os.getenv("REPLAY_QUEUE_NAME",   "event-replay")
USE_SQL_RULES       = os.getenv("USE_SQL_RULES",       "1")    # "1" = load from agl_rules_library; "0" = local YAML fallback
AGENT_VERSION       = os.getenv("AGENT_VERSION",       "1.0.0")