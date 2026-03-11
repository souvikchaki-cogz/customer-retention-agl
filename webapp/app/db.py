import json
import logging
from typing import List, Dict, Any, Optional
import yaml
from datetime import datetime
from shared.sql_client import SqlClient
from shared.config import LOG_LEVEL, DEFAULT_RULESET_YAML_PATH

logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

# Maximum number of CANDIDATE discovery cards allowed in agl_discovery_cards.
# /api/predict will only call generate_triggers() when the live count is below
# this threshold, preventing runaway OpenAI spend on repeated predict clicks.
DISCOVERY_CARDS_MAX = 5


def load_yaml_file(path: str) -> Optional[dict]:
    """Safely load YAML file with logging."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
            logger.debug("Loaded YAML file: %s", path)
            return content
    except FileNotFoundError:
        logger.error("YAML file not found: %s", path)
        return None
    except yaml.YAMLError as e:
        logger.error("YAML loading error in file %s: %s", path, e)
        return None
    except Exception as e:
        logger.error("Unexpected error loading YAML file %s: %s", path, e)
        return None


def fetch_existing_triggers(limit: int = 25) -> List[Dict[str, Any]]:
    """
    Fetch dynamic text rules from dbo.agl_rules_library (NOTE severity),
    then append hardcoded AGL structured signal rules (CORE severity).
    Mirrors the bank application pattern: DB-sourced rules first, CORE rules appended.
    On DB failure, still returns CORE rules gracefully.
    """
    rows: List[Dict[str, Any]] = []
    rule_id_counter = 1

    sql_client = SqlClient()
    try:
        logger.debug("Attempting to fetch dynamic rules from agl_rules_library.")
        result = sql_client.fetch_one(
            "SELECT TOP 1 version, ruleset_yaml FROM dbo.agl_rules_library WHERE status = 'ACTIVE' ORDER BY activated_ts DESC"
        )
        ruleset_yaml_str: Optional[str] = result["ruleset_yaml"] if result and result.get("ruleset_yaml") else None

        if ruleset_yaml_str:
            ruleset = yaml.safe_load(ruleset_yaml_str)
            if ruleset and isinstance(ruleset.get('text_rules'), dict):
                logger.debug("Parsed YAML and found 'text_rules'.")
                for _, rule_value in ruleset['text_rules'].items():
                    if 'description' in rule_value:
                        rows.append({
                            "id": rule_id_counter,
                            "phrase": rule_value['description'],
                            "severity": "NOTE",
                        })
                        rule_id_counter += 1
            else:
                logger.warning("Ruleset YAML is missing 'text_rules' or is not a dict.")
        else:
            logger.info("No ACTIVE ruleset found in dbo.agl_rules_library. Attempting fallback.")
            ruleset = load_yaml_file(DEFAULT_RULESET_YAML_PATH)
            if ruleset and isinstance(ruleset.get('text_rules'), dict):
                logger.info("Fallback loaded sample_rules.yaml text_rules.")
                for _, rule_value in ruleset['text_rules'].items():
                    if 'description' in rule_value:
                        rows.append({
                            "id": rule_id_counter,
                            "phrase": rule_value['description'],
                            "severity": "NOTE",
                        })
                        rule_id_counter += 1
            else:
                logger.error("Fallback ruleset YAML missing 'text_rules' or is empty.")

    except Exception as exc:
        logger.error("Failed to fetch or parse rules from agl_rules_library: %s", exc)

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

    return rows


def fetch_existing_rule_phrases() -> List[str]:
    """
    Return the human-readable description of every approved text rule currently
    in the ACTIVE ruleset, so they can be passed to generate_triggers() as
    exclude_phrases to prevent OpenAI from regenerating already-known triggers.

    Sources (in priority order):
      1. dbo.agl_rules_library – most recent ACTIVE ruleset_yaml
      2. sample_rules.yaml fallback (DEFAULT_RULESET_YAML_PATH)

    Returns an empty list on any error so the caller degrades gracefully.
    """
    phrases: List[str] = []
    try:
        sql_client = SqlClient()
        result = sql_client.fetch_one(
            "SELECT TOP 1 ruleset_yaml FROM dbo.agl_rules_library "
            "WHERE status = 'ACTIVE' ORDER BY activated_ts DESC"
        )
        ruleset_yaml_str: Optional[str] = (
            result["ruleset_yaml"] if result and result.get("ruleset_yaml") else None
        )

        if not ruleset_yaml_str:
            logger.info(
                "fetch_existing_rule_phrases: no ACTIVE ruleset in DB, "
                "falling back to %s", DEFAULT_RULESET_YAML_PATH
            )
            ruleset = load_yaml_file(DEFAULT_RULESET_YAML_PATH)
        else:
            try:
                ruleset = yaml.safe_load(ruleset_yaml_str)
            except yaml.YAMLError as exc:
                logger.error("fetch_existing_rule_phrases: YAML parse error: %s", exc)
                return []

        if ruleset and isinstance(ruleset.get("text_rules"), dict):
            for rule_value in ruleset["text_rules"].values():
                description = (rule_value or {}).get("description")
                if description:
                    phrases.append(str(description))
            logger.debug(
                "fetch_existing_rule_phrases: found %d existing phrases", len(phrases)
            )
        else:
            logger.warning(
                "fetch_existing_rule_phrases: ruleset missing 'text_rules'; "
                "returning empty exclusion list"
            )
    except Exception as exc:
        logger.error("fetch_existing_rule_phrases: unexpected error: %s", exc)

    return phrases


# -----------------------------------------------------------------------------
# agl_discovery_cards helpers
# -----------------------------------------------------------------------------

def count_candidate_discovery_cards() -> int:
    """
    Return the number of rows in agl_discovery_cards with status = 'CANDIDATE'.
    Used by /api/predict to decide whether new triggers need to be generated.
    Returns 0 on any DB error so the caller falls through to generation.
    """
    try:
        sql_client = SqlClient()
        result = sql_client.fetch_one(
            "SELECT COUNT(*) AS cnt FROM dbo.agl_discovery_cards WHERE status = 'CANDIDATE'"
        )
        if result and result.get("cnt") is not None:
            return int(result["cnt"])
        return 0
    except Exception as exc:
        logger.error("count_candidate_discovery_cards failed: %s", exc)
        return 0


def fetch_candidate_discovery_cards() -> List[Dict[str, Any]]:
    """
    Fetch all CANDIDATE rows from agl_discovery_cards ordered by created_ts DESC.
    Returns a list of plain dicts with keys matching the DiscoveryCard model plus
    the explanation columns added in the schema migration:
      discovery_id, phrase, support, lift, odds_ratio, fdr, p_value, examples_json,
      narrative_explanation, support_explanation, lift_explanation,
      odds_ratio_explanation, status
    Returns an empty list on any DB error.
    """
    try:
        sql_client = SqlClient()
        rows = sql_client.fetch_all(
            "SELECT discovery_id, phrase, support, lift, odds_ratio, fdr, p_value, "
            "examples_json, narrative_explanation, support_explanation, "
            "lift_explanation, odds_ratio_explanation, status "
            "FROM dbo.agl_discovery_cards "
            "WHERE status = 'CANDIDATE' "
            "ORDER BY created_ts DESC"
        )
        if not rows:
            return []
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("fetch_candidate_discovery_cards failed: %s", exc)
        return []


def insert_discovery_cards(triggers: List[Dict[str, Any]]) -> int:
    """
    Bulk-insert a list of generated trigger dicts into agl_discovery_cards
    with status = 'CANDIDATE'.

    Each trigger dict must contain:
      description, example_phrases, support (float or dict), lift (float or dict),
      odds_ratio (float or dict), p_value (float), fdr (float),
      narrative_explanation (str), and optionally a metrics_explanation dict
      with keys support, lift, odds_ratio for the explanation text.

    Returns the number of rows successfully inserted.
    Skips individual rows on error and logs the failure.
    """
    if not triggers:
        return 0

    sql_client = SqlClient()
    inserted = 0
    created_ts = datetime.utcnow()

    for t in triggers:
        try:
            phrase = str(t.get("description", ""))[:512]

            # Support both dict-wrapped metrics (from OpenAI path) and bare floats
            # (from any legacy or batch path). This guard prevents AttributeError
            # when the field is a raw float rather than {"value": ..., "explanation": ...}.
            support_raw = t.get("support", 0.0)
            if isinstance(support_raw, dict):
                support = float(support_raw.get("value", 0.0))
                support_explanation = str(support_raw.get("explanation", ""))
            else:
                support = float(support_raw)
                support_explanation = ""

            lift_raw = t.get("lift", 0.0)
            if isinstance(lift_raw, dict):
                lift = float(lift_raw.get("value", 0.0))
                lift_explanation = str(lift_raw.get("explanation", ""))
            else:
                lift = float(lift_raw)
                lift_explanation = ""

            odds_ratio_raw = t.get("odds_ratio", 0.0)
            if isinstance(odds_ratio_raw, dict):
                odds_ratio = float(odds_ratio_raw.get("value", 0.0))
                odds_ratio_explanation = str(odds_ratio_raw.get("explanation", ""))
            else:
                odds_ratio = float(odds_ratio_raw)
                odds_ratio_explanation = ""

            fdr = float(t.get("fdr", 0.0))
            p_value = float(t.get("p_value", 0.0))
            narrative_explanation = str(t.get("narrative_explanation", ""))

            # example_phrases may be a comma-separated string; store as JSON array
            raw_phrases = t.get("example_phrases", "")
            if isinstance(raw_phrases, str):
                phrase_list = [p.strip() for p in raw_phrases.split(",") if p.strip()]
            else:
                phrase_list = list(raw_phrases)
            examples_json = json.dumps(phrase_list)

            sql_client.execute(
                "INSERT INTO dbo.agl_discovery_cards "
                "(phrase, support, lift, odds_ratio, fdr, p_value, examples_json, "
                " narrative_explanation, support_explanation, lift_explanation, "
                " odds_ratio_explanation, status, created_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CANDIDATE', ?)",
                [
                    phrase, support, lift, odds_ratio, fdr, p_value, examples_json,
                    narrative_explanation, support_explanation,
                    lift_explanation, odds_ratio_explanation,
                    created_ts,
                ]
            )
            inserted += 1
        except Exception as exc:
            logger.error("insert_discovery_cards: failed to insert row for phrase=%r: %s", t.get("description"), exc)
            continue

    logger.info("insert_discovery_cards: inserted %d/%d rows", inserted, len(triggers))
    return inserted


def update_discovery_card_status(discovery_id: int, status: str) -> bool:
    """
    Update the status of a single row in agl_discovery_cards.
    status must be 'APPROVED' or 'REJECTED'.
    Returns True if exactly one row was updated, False otherwise.
    """
    if status not in ("APPROVED", "REJECTED"):
        logger.error(
            "update_discovery_card_status: invalid status %r for discovery_id=%s",
            status, discovery_id
        )
        return False
    try:
        sql_client = SqlClient()
        rowcount = sql_client.execute(
            "UPDATE dbo.agl_discovery_cards SET status = ? WHERE discovery_id = ?",
            [status, discovery_id]
        )
        if rowcount != 1:
            logger.warning(
                "update_discovery_card_status: expected 1 row updated for discovery_id=%s, got %s",
                discovery_id, rowcount
            )
            return False
        logger.debug(
            "update_discovery_card_status: discovery_id=%s → %s", discovery_id, status
        )
        return True
    except Exception as exc:
        logger.error(
            "update_discovery_card_status failed for discovery_id=%s: %s", discovery_id, exc
        )
        return False


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
            logger.error("Error bumping semver patch: %s", v)
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
        phrase_hints = [h.strip() for h in (example_phrases or "").split(",") if h.strip()]
    except Exception as e:
        logger.error("Invalid odds_ratio or example_phrases provided: %r, error=%s", odds_ratio, e)
        return False

    sql_client = SqlClient()
    ruleset_yaml_str: Optional[str] = None
    current_version: str = "0.1.0"
    try:
        row = sql_client.fetch_one(
            "SELECT TOP 1 version, ruleset_yaml FROM dbo.agl_rules_library WHERE status = 'ACTIVE' ORDER BY activated_ts DESC"
        )
        if not row or not row.get("ruleset_yaml"):
            logger.info("No ACTIVE ruleset; falling back to most recent by activated_ts")
            row = sql_client.fetch_one(
                "SELECT TOP 1 version, ruleset_yaml FROM dbo.agl_rules_library ORDER BY activated_ts DESC"
            )

        if row and row.get("ruleset_yaml"):
            current_version = row.get("version", "0.1.0")
            ruleset_yaml_str = row.get("ruleset_yaml")
        else:
            logger.warning("No existing ruleset rows found; using standardized YAML fallback")
            ruleset = load_yaml_file(DEFAULT_RULESET_YAML_PATH)
            ruleset_yaml_str = yaml.dump(ruleset) if ruleset else None
            current_version = "0.1.0"

        if ruleset_yaml_str:
            try:
                ruleset = yaml.safe_load(ruleset_yaml_str)
            except yaml.YAMLError as e:
                logger.error("Failed to parse existing ruleset_yaml: %s", e)
                return False
        else:
            logger.error("Failed to find any ruleset YAML for update.")
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
        except yaml.YAMLError as e:
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
    """
    Insert an approved trigger phrase into dbo.agl_triggers (flat display table).

    NOTE: This function is NOT called by the main /api/triggers/approve workflow.
    Trigger approval writes to dbo.agl_rules_library via update_rules_library_with_new_trigger().
    This function is retained for direct or batch inserts into the UI display table only.
    """
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