import logging
from datetime import datetime, timezone
import yaml
from .sql_client import SqlClient
from .azure_openai import get_openai_client
from shared.config import (
    LOG_LEVEL,
    USE_SQL_RULES,
    AZURE_OPENAI_DEPLOYMENTNAME,
    AGENT_VERSION,
    CONFIDENCE_FLOOR,
)

logging.basicConfig(level=LOG_LEVEL)

def load_active_ruleset():
    """
    Loads the active ruleset.
    If USE_SQL_RULES is '1', it attempts to load the latest ACTIVE ruleset from SQL.
    Otherwise, falls back to local sample_rules.yaml file.
    """
    use_sql = USE_SQL_RULES == "1"
    if use_sql:
        try:
            logging.info("Attempting to load ruleset from SQL database...")
            sql_client = SqlClient()
            query = "SELECT TOP 1 ruleset_yaml, version FROM dbo.agl_rules_library WHERE status = 'ACTIVE' ORDER BY activated_ts DESC"
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
        deployment = AZURE_OPENAI_DEPLOYMENTNAME
    except (ValueError, Exception) as e:
        logging.error("AzureOpenAI client could not be initialized (%s). Cannot generate meaningful explanation.", e)
        return " | ".join(explanations)[:1000]

    system_prompt = (
        "You are a helpful assistant for AGL, an Australian energy retailer. "
        "Your task is to summarize the key reasons why an electricity customer might be "
        "at risk of switching to another energy retailer, "
        "based on a list of contributing signals. Present these as a concise, human-readable sentence."
    )

    user_prompt = (
        "Please summarize the following signals into a single, easy-to-understand sentence, "
        "explaining why this customer has been flagged as an energy churn risk:\n\n"
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

    # ── STRUCTURED SIGNAL 1: Property listed for sale/rent (PROACTIVE - highest weight) ──
    # Cross-referenced from property market data against service address.
    # A property appearing on listing platforms that matches a customer address is a near-certain
    # move-out predictor BEFORE the customer even contacts AGL.
    property_listing_status = features.get("property_listing_status")  # e.g. "FOR_SALE", "FOR_RENT", None
    if property_listing_status in ("FOR_SALE", "FOR_RENT"):
        structured_score += weights.get("property_sale_risk", 0.35)
        explanations.append(f"Service address detected as listed {property_listing_status.replace('_', ' ').lower()} on property market")

    # ── STRUCTURED SIGNAL 2: Contract end date within 60 days ──
    # Customers off contract are far more likely to compare and switch.
    try:
        contract_end_str = features.get("contract_end_date")
        if contract_end_str:
            contract_end = datetime.fromisoformat(str(contract_end_str).split(" ")[0]).date()
            days_to_expiry = (contract_end - datetime.now(timezone.utc).date()).days
            if 0 <= days_to_expiry <= 60:
                structured_score += weights.get("contract_expiry_risk", 0.20)
                explanations.append(f"Energy contract expires in {days_to_expiry} days")
    except (ValueError, TypeError) as e:
        logging.warning("Could not parse contract_end_date: %s", e)

    # ── STRUCTURED SIGNAL 3: Bill amount increased >25% quarter-on-quarter ──
    last_bill = features.get("last_bill_amount")
    prev_bill = features.get("prev_bill_amount")
    if last_bill is not None and prev_bill is not None and prev_bill > 0:
        bill_increase_pct = (last_bill - prev_bill) / prev_bill
        if bill_increase_pct > 0.25:
            structured_score += weights.get("bill_shock_risk", 0.20)
            explanations.append(f"Bill increased {bill_increase_pct:.0%} quarter-on-quarter (${prev_bill:.0f} → ${last_bill:.0f})")

    # ── STRUCTURED SIGNAL 4: Conditional discount recently removed or expired ──
    # Removal of a pay-on-time or loyalty discount often triggers immediate comparison behaviour.
    if features.get("conditional_discount_removed"):
        structured_score += weights.get("no_concession_risk", 0.15)
        explanations.append("Conditional discount recently removed or expired")

    # ── TEXT SIGNAL SCORING (unchanged mechanics) ──
    text_hits_json = []
    for h in hits:
        conf = float(h.get("confidence", 0))
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