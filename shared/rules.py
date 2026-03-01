"""Ruleset loader (from SQL or local YAML) and event scorer."""
import os
import json
import math
import yaml
from datetime import datetime, timezone
from .sql_client import SqlClient


def load_active_ruleset():
    use_sql = os.getenv("USE_SQL_RULES", "0") == "1"
    if use_sql:
        try:
            sql_client = SqlClient()
            row = sql_client.fetch_one("""
                SELECT TOP (1) ruleset_yaml, version, activated_ts
                FROM rules_library WHERE status = 'ACTIVE'
                ORDER BY activated_ts DESC
            """)
            if row and row.get("ruleset_yaml"):
                ruleset = yaml.safe_load(row["ruleset_yaml"])
                ruleset["version"] = row["version"]
                return ruleset
        except Exception:
            pass

    path = os.path.join(os.path.dirname(__file__), "..", "sql", "sample_rules.yaml")
    with open(path, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f)
        version = y.get("version", "dev")
        return y, version


def score_event(ruleset: dict, text_result: dict, features: dict):
    weights = ruleset.get("weights", {})
    floor = ruleset.get("confidence_floor", 0.6)
    hits = text_result.get("rule_hits", [])

    structured_score = 0.0
    text_score = 0.0
    explanations = []

    if features.get("rate_diff") is not None:
        val = abs(features["rate_diff"])
        structured_score += min(val / 1.5, 1.0) * weights.get("rate_diff", 0.3)
        explanations.append(
            f"Rate change: {features['prev_rate']} → {features['current_rate']} (Δ={features['rate_diff']})"
        )

    if features.get("account_age_days") is not None:
        months = features["account_age_days"] / 30.0
        structured_score += min(months / 6.0, 1.0) * weights.get("tenure", 0.1)
        explanations.append(f"Tenure ~{months:.1f} months")

    text_hits_json = []
    for h in hits:
        conf = float(h.get("confidence", 0))
        if conf < floor:
            continue
        rid = h["rule_id"]
        w = ruleset.get("text_rules", {}).get(rid, {}).get("weight", 0.4)
        text_score += conf * w
        text_hits_json.append(h)
        if h.get("evidence_text"):
            explanations.append(f'{rid} evidence: \u201c{h["evidence_text"]}\u201d')

    score = max(0.0, min(text_score + structured_score, 1.0))
    details = {
        "rule_hits_json": text_hits_json,
        "explanation_text": " | ".join(explanations)[:1000],
        "agent_version": os.getenv("AGENT_VERSION", "v1"),
    }
    return score, details