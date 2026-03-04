import os
import logging
from typing import List, Dict, Any
import pyodbc
import yaml
from datetime import datetime
from shared.config import (
    AZSQL_SERVER,
    AZSQL_DB,
    AZSQL_UID,
    AZSQL_PWD,
    AZSQL_DRIVER,
    AZSQL_USE_ENTRA,
)

logger = logging.getLogger(__name__)


def _get_sql_config() -> Dict[str, str]:
    return {
        "server": AZSQL_SERVER,
        "database": AZSQL_DB,
        "username": AZSQL_UID,
        "password": AZSQL_PWD,
        "driver": AZSQL_DRIVER,
        # Hard-coded table name per request (schema-qualified)
        "table": "dbo.Triggers",
    }


def _build_conn_str(cfg: Dict[str, str]) -> str:
    """Builds a pyodbc connection string from config, supporting Entra/Managed Identity."""
    base = f'DRIVER={{{cfg["driver"]}}};SERVER={cfg["server"]};DATABASE={cfg["database"]};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;'

    # Use shared config for Entra ID
    if AZSQL_USE_ENTRA == "1":
        return f"{base}Authentication=ActiveDirectoryMsi;"
    else:
        return f'{base}UID={cfg["username"]};PWD={cfg["password"]};'


def fetch_existing_triggers(limit: int = 25) -> List[Dict[str, Any]]:
    """
    Fetch rules from the rules_library table and combine them with
    hardcoded customer profile rules.
    """
    cfg = _get_sql_config()
    use_entra = AZSQL_USE_ENTRA == "1"
    creds_ok = use_entra or all([cfg["username"], cfg["password"]]) # username/pwd can be empty for Entra
    if not all([cfg["server"], cfg["database"]]) or not creds_ok:
        logger.info("Azure SQL config incomplete; returning empty trigger list")
        return []
    if pyodbc is None:
        logger.warning("pyodbc not installed; cannot fetch triggers; returning empty list")
        return []

    rows: List[Dict[str, Any]] = []
    rule_id_counter = 1

    # 1. Fetch rules from database
    query = "SELECT TOP 1 ruleset_yaml FROM dbo.rules_library WHERE status = 'ACTIVE' ORDER BY activated_ts DESC"
    conn_str = _build_conn_str(cfg)
    try:
        with pyodbc.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version, ruleset_yaml FROM dbo.rules_library WHERE status = 'ACTIVE' ORDER BY activated_ts DESC")
                active_ruleset = cur.fetchone()

                if active_ruleset:
                    current_version, ruleset_yaml_str = active_ruleset
                    ruleset = yaml.safe_load(ruleset_yaml_str)
                    if ruleset and 'text_rules' in ruleset:
                        for _, rule_value in ruleset['text_rules'].items():
                            if 'description' in rule_value:
                                rows.append({
                                    "id": rule_id_counter,
                                    "phrase": rule_value['description'],
                                    "severity": "NOTE",
                                })
                                rule_id_counter += 1
    except Exception as exc:
        logger.error("Failed to fetch rules from rules_library: %s", exc)
        # Don't return here, still want to add hardcoded rules

    # 2. Add hardcoded customer profile rules
    core_systems_rules = [
      "Loan tenure is between 1-6 years",
      "Broker originated loan",
      "Interest rate is 0.5% higher than advertised rate",
      "Interest only loan term coming to an end"
    ]

    for rule in core_systems_rules:
        rows.append({
            "id": rule_id_counter,
            "phrase": rule,
            "severity": "CORE",
        })
        rule_id_counter += 1

    return rows


def update_rules_library_with_new_trigger(phrase: str, example_phrases: str, odds_ratio: float) -> bool:
    """
    Rewrite: Insert a new ACTIVE ruleset row in dbo.rules_library with an updated ruleset_yaml
    that includes a newly approved text rule.

    Contract:
    - Inputs: phrase (str), example_phrases (comma-separated str), odds_ratio (float)
    - Effects:
      * Deactivate all other rows (status = INACTIVE)
      * Insert one new row with: version bumped (semantic patch), status=ACTIVE,
        activated_ts=now, ruleset_yaml updated with new rule
      * Inside YAML, update 'version' to the same value as the column version
      * New rule id auto-increments from existing max id (e.g., T9 -> T10)
      * weight = round(odds_ratio/10, 3), phrase_hints from example_phrases split by ','
      * negations present as empty list
    - Returns: True on success, False on failure. Logs reasons at INFO/WARNING/ERROR.
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
            # Fallback to 0.1.0 -> 0.1.1
            return "0.1.1"

    def _safe_slug(s: str, max_len: int = 40) -> str:
        base = (s or "").upper().strip().replace("-", "_").replace(" ", "_")
        cleaned = []
        for ch in base:
            if ch.isalnum() or ch == "_":
                cleaned.append(ch)
        slug = "".join(cleaned)
        # collapse multiple underscores
        while "__" in slug:
            slug = slug.replace("__", "_")
        slug = slug.strip("_")
        return slug[:max_len] or "AUTO_RULE"

    def _extract_max_t_id(text_rules: dict) -> int:
        max_id = 0
        for key, val in (text_rules or {}).items():
            # Prefer inner 'id' like "T7"
            inner = (val or {}).get("id")
            candidate = None
            if isinstance(inner, str) and inner.startswith("T"):
                # parse consecutive digits after T
                i = 1
                while i < len(inner) and inner[i].isdigit():
                    i += 1
                num = inner[1:i]
                if num.isdigit():
                    candidate = int(num)
            if candidate is None and isinstance(key, str) and key.startswith("T"):
                # parse from key prefix
                i = 1
                while i < len(key) and key[i].isdigit():
                    i += 1
                num = key[1:i]
                if num.isdigit():
                    candidate = int(num)
            if candidate is not None:
                max_id = max(max_id, candidate)
        return max_id

    cfg = _get_sql_config()
    use_entra = AZSQL_USE_ENTRA == "1"
    creds_ok = use_entra or all([cfg["username"], cfg["password"]]) # username/pwd can be empty for Entra
    if not all([cfg["server"], cfg["database"]]) or not creds_ok:
        logger.error("Azure SQL config incomplete; cannot update rules_library")
        return False
    if pyodbc is None:  # type: ignore
        logger.error("pyodbc not installed; cannot update rules_library")
        return False

    # Normalize inputs
    try:
        weight = round(float(odds_ratio) / 10.0, 3)
    except Exception:
        logger.error("Invalid odds_ratio provided: %r", odds_ratio)
        return False
    phrase_hints = [h.strip() for h in (example_phrases or "").split(",") if h.strip()]

    conn_str = _build_conn_str(cfg)
    try:
        with pyodbc.connect(conn_str, autocommit=False) as conn:  # type: ignore
            with conn.cursor() as cur:  # type: ignore
                # 1) Fetch current active ruleset (fallback to latest if no ACTIVE)
                cur.execute(
                    "SELECT TOP 1 version, ruleset_yaml FROM dbo.rules_library WHERE status = 'ACTIVE' ORDER BY activated_ts DESC"
                )
                row = cur.fetchone()
                if not row:
                    logger.info("No ACTIVE ruleset; falling back to most recent by activated_ts")
                    cur.execute(
                        "SELECT TOP 1 version, ruleset_yaml FROM dbo.rules_library ORDER BY activated_ts DESC"
                    )
                    row = cur.fetchone()

                ruleset_yaml_str: str | None = None
                current_version: str = "0.1.0"
                if row:
                    current_version, ruleset_yaml_str = row[0], row[1]
                else:
                    logger.warning("No existing ruleset rows found; attempting to bootstrap from sample_rules.yaml")
                    # Bootstrap from local sample if available
                    try:
                        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
                        sample_path = os.path.join(root_dir, "sample_rules.yaml")
                        with open(sample_path, "r", encoding="utf-8") as f:
                            ruleset_yaml_str = f.read()
                        current_version = "0.1.0"
                    except Exception as e:
                        logger.error("Unable to bootstrap ruleset from sample_rules.yaml: %s", e)
                        conn.rollback()
                        return False

                # 2) Parse YAML
                try:
                    ruleset = yaml.safe_load(ruleset_yaml_str or "") or {}
                except Exception as e:
                    logger.error("Failed to parse existing ruleset_yaml: %s", e)
                    conn.rollback()
                    return False

                # Ensure text_rules structure exists
                text_rules = ruleset.get("text_rules")
                if not isinstance(text_rules, dict):
                    logger.error("ruleset_yaml missing 'text_rules' dict; cannot proceed")
                    conn.rollback()
                    return False

                # 3) Compute new id and key
                max_id_num = _extract_max_t_id(text_rules)
                new_num = max_id_num + 1
                new_id = f"T{new_num}"
                slug = _safe_slug(phrase)
                new_key = f"{new_id}_{slug}"

                # 4) Add new rule entry
                new_rule = {
                    "id": new_id,
                    "description": phrase,
                    "weight": weight,
                    "phrase_hints": phrase_hints,
                    "negations": [],
                }
                text_rules[new_key] = new_rule

                # 5) Bump version and set inside YAML
                new_version = _bump_semver_patch(current_version)
                ruleset["version"] = str(new_version)

                # 6) Dump YAML (preserve key order)
                try:
                    new_ruleset_yaml = yaml.dump(ruleset, sort_keys=False, indent=2)
                except Exception as e:
                    logger.error("Failed to serialize updated ruleset_yaml: %s", e)
                    conn.rollback()
                    return False

                # 7) Deactivate all existing rows, then insert new ACTIVE ruleset
                try:
                    cur.execute("UPDATE dbo.rules_library SET status = 'INACTIVE' WHERE status <> 'INACTIVE'")
                    insert_sql = (
                        "INSERT INTO dbo.rules_library (version, status, activated_ts, ruleset_yaml) "
                        "VALUES (?, 'ACTIVE', ?, ?)"
                    )
                    activated_ts = datetime.utcnow()
                    cur.execute(insert_sql, new_version, activated_ts, new_ruleset_yaml)
                except Exception as e:
                    logger.error("Failed to write updated ruleset to database: %s", e)
                    conn.rollback()
                    return False

                conn.commit()
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
        logger.error("Unexpected failure updating rules_library: %s", exc)
        return False


def insert_trigger(phrase: str, severity: str) -> bool:
    """Insert an approved trigger into dbo.Triggers.

    Returns True on success, False on any failure (including missing config / driver).
    """
    cfg = _get_sql_config()
    use_entra = AZSQL_USE_ENTRA == "1"
    creds_ok = use_entra or all([cfg["username"], cfg["password"]]) # username/pwd can be empty for Entra
    if not all([cfg["server"], cfg["database"]]) or not creds_ok:
        logger.info("Azure SQL config incomplete; cannot insert trigger")
        return False
    if pyodbc is None:  # type: ignore
        logger.warning("pyodbc not installed; cannot insert trigger")
        return False
    conn_str = _build_conn_str(cfg)
    try:
        with pyodbc.connect(conn_str) as conn:  # type: ignore
            with conn.cursor() as cur:  # type: ignore
                cur.execute(f"INSERT INTO {cfg['table']} (trigger_text, severity) VALUES (?, ?)", phrase, severity)
                conn.commit()
        logger.debug("Inserted trigger phrase=%s severity=%s", phrase, severity)
        return True
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to insert trigger: %s", exc)
        return False


def delete_trigger(trigger_id: int) -> bool:
    """Delete a trigger by id. Returns True if a row was deleted."""
    cfg = _get_sql_config()
    use_entra = AZSQL_USE_ENTRA == "1"
    creds_ok = use_entra or all([cfg["username"], cfg["password"]]) # username/pwd can be empty for Entra
    if not all([cfg["server"], cfg["database"]]) or not creds_ok:
        logger.info("Azure SQL config incomplete; cannot delete trigger")
        return False
    if pyodbc is None:  # type: ignore
        logger.warning("pyodbc not installed; cannot delete trigger")
        return False
    conn_str = _build_conn_str(cfg)
    try:
        with pyodbc.connect(conn_str) as conn:  # type: ignore
            with conn.cursor() as cur:  # type: ignore
                cur.execute(f"DELETE FROM {cfg['table']} WHERE trigger_id = ?", trigger_id)
                deleted = cur.rowcount
                conn.commit()
        logger.debug("Deleted trigger id=%s affected=%s", trigger_id, deleted)
        return deleted > 0
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to delete trigger id=%s error=%s", trigger_id, exc)
        return False