import os
import logging
from typing import List, Dict, Any
import yaml
from datetime import datetime
from shared.sql_client import SqlClient

logger = logging.getLogger(__name__)

def fetch_existing_triggers(limit: int = 25) -> List[Dict[str, Any]]:
    """
    Fetch rules from the agl_rules_library table and combine them with
    hardcoded customer profile rules.
    """
    rows: List[Dict[str, Any]] = []
    rule_id_counter = 1

    core_systems_rules = [
        "Service address detected as listed for sale on property market",
        "Service address detected as listed for rent on property market",
        "Energy contract expiring within 60 days",
        "Bill amount increased >25% quarter-on-quarter",
        "Conditional discount recently removed or expired",
    ]

    for rule in core_systems_rules:
        rows.append({
            "id": rule_id_counter,
            "phrase": rule,
            "severity": "CORE",
        })
        rule_id_counter += 1

    try:
        logger.debug("Attempting to fetch dynamic rules from agl_rules_library.")
        sql_client = SqlClient()
        result = sql_client.fetch_one(
            "SELECT TOP 1 version, ruleset_yaml FROM dbo.agl_rules_library WHERE status = 'ACTIVE' ORDER BY activated_ts DESC"
        )
        if result and result.get("ruleset_yaml"):
            logger.debug("Found an ACTIVE ruleset in the database.")
            ruleset_yaml_str = result["ruleset_yaml"]
            ruleset = yaml.safe_load(ruleset_yaml_str)
            if ruleset and 'text_rules' in ruleset:
                logger.debug("Successfully parsed YAML and found 'text_rules'.")
                for _, rule_value in ruleset['text_rules'].items():
                    if 'description' in rule_value:
                        rows.append({
                            "id": rule_id_counter,
                            "phrase": rule_value['description'],
                            "severity": "NOTE",
                        })
                        rule_id_counter += 1
            else:
                logger.warning("Ruleset YAML was loaded but is missing 'text_rules' key or is empty.")
        else:
            logger.info("No ACTIVE ruleset found in dbo.agl_rules_library.")
    except Exception as exc:
        logger.error("Failed to fetch rules from agl_rules_library: %s", exc)

    return rows

def update_rules_library_with_new_trigger(phrase: str, example_phrases: str, odds_ratio: float) -> bool:
    """
    Insert a new ACTIVE ruleset row in dbo.agl_rules_library with an updated ruleset_yaml
    including a newly approved text rule.
    """
    def _bump_semver_patch(v: str) -> str:
        try:
            parts = str(v).strip().split(".")
            while len(parts) < 3:
                parts.append("0")
            major, minor, patch = parts[0], parts[1], parts[2]
            patch_i = int(patch) if patch.isdigit() else 0
            return f"{major}.{minor}.{patch_i + 1}"
        except Exception:
            return "0.1.1"

    def _safe_slug(s: str, max_len: int = 40) -> str:
        base = (s or "").upper().strip().replace("-", "_").replace(" ", "_")
        cleaned = []
        for ch in base:
            if ch.isalnum() or ch == "_":
                cleaned.append(ch)
        slug = "".join(cleaned)
        while "__" in slug:
            slug = slug.replace("__", "_")
        slug = slug.strip("_")
        return slug[:max_len] or "AUTO_RULE"

    def _extract_max_t_id(text_rules: dict) -> int:
        max_id = 0
        for key, val in (text_rules or {}).items():
            inner = (val or {}).get("id")
            candidate = None
            if isinstance(inner, str) and inner.startswith("T"):
                i = 1
                while i < len(inner) and inner[i].isdigit():
                    i += 1
                num = inner[1:i]
                if num.isdigit():
                    candidate = int(num)
            if candidate is None and isinstance(key, str) and key.startswith("T"):
                i = 1
                while i < len(key) and key[i].isdigit():
                    i += 1
                num = key[1:i]
                if num.isdigit():
                    candidate = int(num)
            if candidate is not None:
                max_id = max(max_id, candidate)
        return max_id

    try:
        weight = round(float(odds_ratio) / 10.0, 3)
    except Exception:
        logger.error("Invalid odds_ratio provided: %r", odds_ratio)
        return False
    phrase_hints = [h.strip() for h in (example_phrases or "").split(",") if h.strip()]

    sql_client = SqlClient()
    try:
        row = sql_client.fetch_one(
            "SELECT TOP 1 version, ruleset_yaml FROM dbo.agl_rules_library WHERE status = 'ACTIVE' ORDER BY activated_ts DESC"
        )
        if not row or not row.get("ruleset_yaml"):
            logger.info("No ACTIVE ruleset; falling back to most recent by activated_ts")
            row = sql_client.fetch_one(
                "SELECT TOP 1 version, ruleset_yaml FROM dbo.agl_rules_library ORDER BY activated_ts DESC"
            )

        ruleset_yaml_str: str | None = None
        current_version: str = "0.1.0"
        if row and row.get("ruleset_yaml"):
            current_version = row.get("version", "0.1.0")
            ruleset_yaml_str = row.get("ruleset_yaml")
        else:
            logger.warning("No existing ruleset rows found; attempting to bootstrap from sample_rules.yaml")
            try:
                root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                sample_path = os.path.join(root_dir, "sample_rules.yaml")
                with open(sample_path, "r", encoding="utf-8") as f:
                    ruleset_yaml_str = f.read()
                current_version = "0.1.0"
            except Exception as e:
                logger.error("Unable to bootstrap ruleset from sample_rules.yaml: %s", e)
                return False

        try:
            ruleset = yaml.safe_load(ruleset_yaml_str or "") or {}
        except Exception as e:
            logger.error("Failed to parse existing ruleset_yaml: %s", e)
            return False

        text_rules = ruleset.get("text_rules")
        if not isinstance(text_rules, dict):
            logger.error("ruleset_yaml missing 'text_rules' dict; cannot proceed")
            return False

        max_id_num = _extract_max_t_id(text_rules)
        new_num = max_id_num + 1
        new_id = f"T{new_num}"
        slug = _safe_slug(phrase)
        new_key = f"{new_id}_{slug}"

        new_rule = {
            "id": new_id,
            "description": phrase,
            "weight": weight,
            "phrase_hints": phrase_hints,
            "negations": [],
        }
        text_rules[new_key] = new_rule

        new_version = _bump_semver_patch(current_version)
        ruleset["version"] = str(new_version)

        try:
            new_ruleset_yaml = yaml.dump(ruleset, sort_keys=False, indent=2)
        except Exception as e:
            logger.error("Failed to serialize updated ruleset_yaml: %s", e)
            return False

        try:
            deactivate_sql = "UPDATE dbo.agl_rules_library SET status = 'INACTIVE' WHERE status <> 'INACTIVE'"
            insert_sql = (
                "INSERT INTO dbo.agl_rules_library (version, status, activated_ts, ruleset_yaml) "
                "VALUES (?, 'ACTIVE', ?, ?)"
            )
            activated_ts = datetime.utcnow()

            sql_client.execute(deactivate_sql)
            sql_client.execute(insert_sql, [new_version, activated_ts, new_ruleset_yaml])

        except Exception as e:
            logger.error("Failed to write updated ruleset to database: %s", e)
            return False

        logger.info(
            "Rules library updated: version %s -> %s, new rule %s added (weight=%s, hints=%d)",
            current_version,
            new_version,
            new_id,
            weight,
            len(phrase_hints),
        )
        return True
    except Exception as exc:
        logger.error("Unexpected failure updating agl_rules_library: %s", exc)
        return False

def insert_trigger(phrase: str, severity: str) -> bool:
    try:
        sql_client = SqlClient()
        sql_client.execute(
            "INSERT INTO dbo.agl_triggers (trigger_text, severity) VALUES (?, ?)",
            [phrase, severity]
        )
        logger.debug("Inserted trigger phrase=%s severity=%s", phrase, severity)
        return True
    except Exception as exc:
        logger.error("Failed to insert trigger: %s", exc)
        return False

def delete_trigger(trigger_id: int) -> bool:
    try:
        sql_client = SqlClient()
        rowcount = sql_client.execute(
            "DELETE FROM dbo.agl_triggers WHERE trigger_id = ?",
            [trigger_id]
        )
        logger.debug("Deleted trigger id=%s affected=%s", trigger_id, rowcount)
        return rowcount > 0
    except Exception as exc:
        logger.error("Failed to delete trigger id=%s error=%s", trigger_id, exc)
        return False