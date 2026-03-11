"""
This script uses Azure OpenAI to generate synthetic customer retention triggers and saves them
as candidates in the discovery_cards table for review and approval.
"""
import json
import yaml
from shared.sql_client import SqlClient
from shared.discovery import generate_triggers
from shared.config import LOG_LEVEL  # Optionally use logging config here

import logging
logging.basicConfig(level=LOG_LEVEL if LOG_LEVEL else "INFO")

def write_discovery_cards(sql_client: SqlClient, triggers: list):
    """
    Writes the generated triggers to the discovery_cards table.
    """
    for trigger in triggers:
        sql = """
        INSERT INTO dbo.agl_discovery_cards (phrase, support, lift, odds_ratio, p_value, fdr, examples_json,
            narrative_explanation, support_explanation, lift_explanation, odds_ratio_explanation,
            status, created_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CANDIDATE', SYSDATETIME())
        """
        # Map the richer trigger format from the shared function to the database schema.
        # Support both dict-wrapped metrics ({"value": ..., "explanation": ...}) and bare
        # floats — the same guard used in webapp/app/db.py insert_discovery_cards().
        # Without this, trigger.get("support", {}).get("value", 0.0) raises AttributeError
        # when "support" is a raw float rather than a dict.
        support_raw = trigger.get("support", 0.0)
        if isinstance(support_raw, dict):
            support_val = float(support_raw.get("value", 0.0))
            support_explanation = str(support_raw.get("explanation", ""))
        else:
            support_val = float(support_raw)
            support_explanation = ""

        lift_raw = trigger.get("lift", 0.0)
        if isinstance(lift_raw, dict):
            lift_val = float(lift_raw.get("value", 0.0))
            lift_explanation = str(lift_raw.get("explanation", ""))
        else:
            lift_val = float(lift_raw)
            lift_explanation = ""

        odds_ratio_raw = trigger.get("odds_ratio", 0.0)
        if isinstance(odds_ratio_raw, dict):
            odds_ratio_val = float(odds_ratio_raw.get("value", 0.0))
            odds_ratio_explanation = str(odds_ratio_raw.get("explanation", ""))
        else:
            odds_ratio_val = float(odds_ratio_raw)
            odds_ratio_explanation = ""

        narrative_explanation = str(trigger.get("narrative_explanation", ""))

        example_phrases = trigger.get("example_phrases", "").split(",")
        examples_json = json.dumps([p.strip() for p in example_phrases if p.strip()])

        sql_client.execute(sql, params=[
            trigger.get("description"),
            support_val,
            lift_val,
            odds_ratio_val,
            float(trigger.get("p_value", 0.0)),
            float(trigger.get("fdr", 0.0)),
            examples_json,
            narrative_explanation,
            support_explanation,
            lift_explanation,
            odds_ratio_explanation,
        ])
    logging.info(f"Successfully inserted {len(triggers)} new triggers into discovery_cards.")

def main():
    """
    Main function to run the discovery workflow.
    """
    logging.info("Starting synthetic trigger generation workflow...")
    sql_client = SqlClient()

    # Get existing rules to avoid duplicates and semantic overlap.
    # We extract the human-readable 'description' from each rule (not the YAML key name)
    # so that the LLM can reason about the *meaning* of existing triggers and avoid
    # generating anything semantically equivalent, regardless of wording.
    current_ruleset_query = "SELECT TOP 1 ruleset_yaml FROM dbo.agl_rules_library WHERE status = 'ACTIVE' ORDER BY activated_ts DESC"
    current_ruleset_result = sql_client.fetch_one(current_ruleset_query)
    existing_phrases = []
    if current_ruleset_result:
        try:
            existing_rules = yaml.safe_load(current_ruleset_result['ruleset_yaml']) or {}
            for rule_value in existing_rules.get("text_rules", {}).values():
                desc = rule_value.get("description") if isinstance(rule_value, dict) else None
                if desc:
                    existing_phrases.append(desc)
        except (yaml.YAMLError, KeyError) as e:
            logging.error(f"Error parsing existing rules: {e}")

    # Generate synthetic triggers
    logging.info(f"Generating new triggers, excluding {len(existing_phrases)} existing descriptions.")
    new_triggers = generate_triggers(exclude_phrases=existing_phrases)

    if not new_triggers:
        logging.warning("No new triggers were generated.")
        return

    logging.info(f"Generated {len(new_triggers)} new triggers to be reviewed.")

    # Write the new triggers to the discovery_cards table for review
    write_discovery_cards(sql_client, new_triggers)

    logging.info("Discovery workflow completed. New triggers are ready for review in the discovery_cards table.")

if __name__ == "__main__":
    main()