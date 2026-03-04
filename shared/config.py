"""
Centralized configuration for Customer Retention Unified Repo.
"""

import os

def _get_float(var, default):
    try:
        return float(os.getenv(var, default))
    except Exception:
        return float(default)

def _get_int(var, default):
    try:
        return int(os.getenv(var, default))
    except Exception:
        return int(default)

LEAD_SCORE_THRESHOLD = _get_float("LEAD_SCORE_THRESHOLD", "0.7")
CONFIDENCE_FLOOR = _get_float("CONFIDENCE_FLOOR", "0.60")
EVIDENCE_MIN_LEN = _get_int("EVIDENCE_MIN_LEN", "4")

# Database and OpenAI config
AZSQL_SERVER = os.getenv("AZSQL_SERVER", "")
AZSQL_DB = os.getenv("AZSQL_DB", "")
AZSQL_UID = os.getenv("AZSQL_UID", "")
AZSQL_PWD = os.getenv("AZSQL_PWD", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")

# Azure Functions config
FUNCTION_START_URL = os.getenv("FUNCTION_START_URL", "")
FUNCTION_BASE_URL = os.getenv("FUNCTION_BASE_URL", "http://localhost:7071")
FUNCTION_CODE = os.getenv("FUNCTION_CODE", "")

# Other
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
REPLAY_QUEUE_NAME = os.getenv("REPLAY_QUEUE_NAME", "event-replay")
AZSQL_DRIVER = os.getenv("AZSQL_DRIVER", "{ODBC Driver 18 for SQL Server}")
AZSQL_USE_ENTRA = os.getenv("AZSQL_USE_ENTRA", "0")
USE_SQL_RULES = os.getenv("USE_SQL_RULES", "1")
AGENT_VERSION = os.getenv("AGENT_VERSION", "1.0.0")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")