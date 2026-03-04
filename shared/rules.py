import logging
from datetime import datetime, timezone
import yaml
from .sql_client import SqlClient
from .azure_openai import get_openai_client
from shared.config import (
    USE_SQL_RULES,
    AZURE_OPENAI_DEPLOYMENT,
    AGENT_VERSION,
    CONFIDENCE_FLOOR,
)

logging.basicConfig(level=logging.INFO)

def load_active_ruleset():
    """
    Loads the active ruleset.
    If USE_SQL_RULES is '1', it attempts to load the latest ACTIVE ruleset from SQL.
    Otherwise, falls back to local sample_rules.yaml file.
    """
    use_sql = USE_SQL_RULES == "1" if isinstance(USE_SQL_RULES, str) else bool(USE_SQL_RULES)
    if use_sql:
        try:
            logging.info("Attempting to load ruleset from SQL database...")
            sql_client = SqlClient()
            query = "SELECT TOP 1 ruleset_yaml, version FROM dbo.rules_library WHERE status = 'ACTIVE' ORDER BY activated_ts DESC"
            result = sql_client.fetch_one(query)
            if result and result.get('ruleset_yaml'):
                logging.info("Successfully loaded active ruleset from SQL.")
                ruleset_yaml = result['ruleset_yaml']
                y = yaml.safe_load(ruleset_yaml)
                version = result.get("version", y.get("version", "unknown_sql_version"))
                return y, version
            else:
                logging.warning("No active ruleset found in SQL. Falling back to local file.")
        except Exception as e:
            logging.error("Failed to load ruleset from SQL due to: %s. Falling back to local file.", e)
    # Fallback to file-based for local dev or if SQL fails
    logging.info("Loading rules from local fallback file (sample_rules.yaml).")
    try:
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "sample_rules.yaml")
        with open(path, "r", encoding="utf-8") as f:
            y = yaml.safe_load(f)
            version = y.get("version", "dev_fallback")
            return y, version
    except Exception as e:
        logging.error("FATAL: Could not load fallback ruleset file: %s", e)
        return {}, "fallback_failed"

def get_meaningful_explanation(explanations: list) -> str:
    """
    Generates a meaningful explanation by summarizing a list of explanation points using an LLM.
    """
    try:
        client = get_openai_client()
        deployment = AZURE_OPENAI_DEPLOYMENT
    except (ValueError, Exception) as e:
        logging.error("AzureOpenAI client could not be initialized (%s). Cannot generate meaningful explanation.", e)
        return " | ".join(explanations)[:1000]

    system_prompt = (
        "You are a helpful assistant for a bank. "
        "Your task is to summarize the key reasons why a customer might be at risk of leaving the bank, "
        "based on a list of contributing factors. Present these factors as a concise, human-readable sentence."
    )

    user_prompt = (
        "Please summarize the following points into a single, easy-to-understand sentence, "
        "explaining why this customer has been flagged as a retention risk:\n\n"
        + "\n".join(explanations)
    )

    try:
        logging.info("Calling Azure OpenAI to generate a meaningful explanation. Model: %s", deployment)
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=150
        )
        meaningful_explanation = resp.choices[0].message.content.strip()
        logging.info("Successfully generated meaningful explanation.")
        return meaningful_explanation

    except Exception as e:
        logging.error("Error generating meaningful explanation: %s", e, exc_info=True)
        # Fallback to the original simple join
        return " | ".join(explanations)[:1000]

def score_event(ruleset: dict, text_result: dict, features: dict):
    weights = ruleset.get("weights", {})
    floor = ruleset.get("confidence_floor", CONFIDENCE_FLOOR)

    hits = text_result.get("rule_hits", [])
    structured_score = 0.0
    text_score = 0.0
    explanations = []

    # --- Structured Rules Implementation ---
    remaining_years = features.get("remaining_years")
    if remaining_years is not None and 1.0 <= remaining_years <= 6.0:
        structured_score += weights.get("tenure_risk", 0.15)
        explanations.append(f"Loan tenure is critical ({remaining_years:.1f} years remaining)")

    if features.get("is_broker_originated"):
        structured_score += weights.get("broker_risk", 0.1)
        explanations.append("Broker-originated loan")

    advertised_rate = features.get("advertised_rate")
    current_rate = features.get("interest_rate")
    if advertised_rate is not None and current_rate is not None and current_rate > (advertised_rate + 0.5):
        structured_score += weights.get("rate_delta_risk", 0.2)
        explanations.append(f"Rate ({current_rate:.2f}%) is >0.5% above advertised ({advertised_rate:.2f}%)")

    try:
        if features.get("is_interest_only"):
            end_date_str = features.get("interest_only_end_date")
            if end_date_str:
                end_date = datetime.fromisoformat(str(end_date_str).split(" ")[0]).date()
                days_to_expiry = (end_date - datetime.now(timezone.utc).date()).days
                if 0 <= days_to_expiry <= 90:
                    structured_score += weights.get("io_expiry_risk", 0.25)
                    explanations.append(f"Interest-only term expires in {days_to_expiry} days")
    except (ValueError, TypeError) as e:
        logging.warning("Could not parse interest_only_end_date: %s", e)

    text_hits_json = []
    for h in hits:
        conf = float(h.get("confidence", 0))
        # Optionally: if conf < floor: continue  # (unified via config if logic is used)
        rid = h["rule_id"]
        w = ruleset.get("text_rules", {}).get(rid, {}).get("weight", 0.4)
        text_score += conf * w
        text_hits_json.append(h)
        if h.get("evidence_text"):
            explanations.append(rid + " evidence: \"" + h['evidence_text'] + "\"")

    score = max(0.0, min(text_score + structured_score, 1.0))
    explanation_text = get_meaningful_explanation(explanations)

    details = {
        "rule_hits_json": text_hits_json,
        "explanation_text": explanation_text,
        "agent_version": AGENT_VERSION,
    }
    return score, details