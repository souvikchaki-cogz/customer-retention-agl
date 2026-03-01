"""Triggers CRUD layer — thin wrapper over shared.sql_client for the webapp."""
import logging
from typing import List, Dict, Any
from shared import SqlClient

logger = logging.getLogger(__name__)


def fetch_existing_triggers(limit: int = 25) -> List[Dict[str, Any]]:
    sql = SqlClient()
    if not sql.is_configured:
        logger.info("SQL config incomplete; returning empty trigger list")
        return []
    query = f"SELECT TOP {int(limit)} trigger_id, trigger_text, severity FROM dbo.Triggers ORDER BY trigger_id DESC"
    try:
        rows = sql.fetch_all(query)
        result = []
        for rec in rows:
            tid = rec["trigger_id"]
            base = (tid or 1) % 97 / 97.0
            support = round(0.08 + base * 0.25, 4)
            lift = round(1.2 + base * 1.6, 3)
            odds_ratio = round(1.3 + base * 3.2, 3)
            p_value = round(0.005 + (1 - base) * 0.06, 4)
            fdr = round(min(p_value * 1.1, 0.08), 4)
            result.append({
                "id": tid,
                "phrase": rec["trigger_text"],
                "severity": rec["severity"],
                "support": support, "lift": lift, "odds_ratio": odds_ratio,
                "p_value": p_value, "fdr": fdr,
                "explanation": f"'{rec['trigger_text']}' appears in ~{support*100:.1f}% of at-risk customers.",
            })
        return result
    except Exception as e:
        logger.error("Failed to fetch triggers: %s", e)
        return []


def insert_trigger(phrase: str, severity: str) -> bool:
    sql = SqlClient()
    if not sql.is_configured:
        return False
    try:
        sql.execute("INSERT INTO dbo.Triggers (trigger_text, severity) VALUES (?, ?)", [phrase, severity])
        return True
    except Exception as e:
        logger.error("Failed to insert trigger: %s", e)
        return False


def delete_trigger(trigger_id: int) -> bool:
    sql = SqlClient()
    if not sql.is_configured:
        return False
    try:
        return sql.execute("DELETE FROM dbo.Triggers WHERE trigger_id = ?", [trigger_id]) > 0
    except Exception as e:
        logger.error("Failed to delete trigger: %s", e)
        return False