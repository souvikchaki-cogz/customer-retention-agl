"""
This script uses Azure OpenAI to generate synthetic customer retention triggers and saves them
as candidates in the discovery_cards table for review and approval.
"""
import json
import os
from openai import AzureOpenAI
import yaml
from shared.sql_client import SqlClient
from shared.discovery import generate_triggers

def write_discovery_cards(sql_client: SqlClient, triggers: list):
    """
    Writes the generated triggers to the discovery_cards table.
    """
    for trigger in triggers:
        sql = """
        INSERT INTO discovery_cards (phrase, support, lift, odds_ratio, fdr, examples_json, status, created_ts)
        VALUES (?, ?, ?, ?, ?, ?, 'CANDIDATE', SYSDATETIME())
        """
        # Map the richer trigger format from the shared function to the database schema
        example_phrases = trigger.get("example_phrases", "").split(",")
        examples_json = json.dumps([p.strip() for p in example_phrases if p.strip()])

        sql_client.fetch_one(sql, params=[
            trigger.get("description"),
            float(trigger.get("support", {}).get("value", 0.0)),
            float(trigger.get("lift", {}).get("value", 0.0)),
            float(trigger.get("odds_ratio", {}).get("value", 0.0)),
            float(trigger.get("fdr", 0.0)),
            examples_json
        ])
    print(f"Successfully inserted {len(triggers)} new triggers into discovery_cards.")

def main():
    """
    Main function to run the discovery workflow.
    """
    print("Starting synthetic trigger generation workflow...")
    sql_client = SqlClient()
    
    # Get existing rules to avoid duplicates
    current_ruleset_query = "SELECT ruleset_yaml FROM rules_library WHERE status = 'ACTIVE'"
    current_ruleset_result = sql_client.fetch_one(current_ruleset_query)
    existing_phrases = []
    if current_ruleset_result:
        try:
            existing_rules = yaml.safe_load(current_ruleset_result['ruleset_yaml']) or {}
            existing_phrases = list(existing_rules.get("text_rules", {}).keys())
        except (yaml.YAMLError, KeyError) as e:
            print(f"Error parsing existing rules: {e}")

    # Generate synthetic triggers
    print(f"Generating new triggers, excluding {len(existing_phrases)} existing phrases.")
    new_triggers = generate_triggers(exclude_phrases=existing_phrases)

    if not new_triggers:
        print("No new triggers were generated.")
        return

    print(f"Generated {len(new_triggers)} new triggers to be reviewed.")

    # Write the new triggers to the discovery_cards table for review
    write_discovery_cards(sql_client, new_triggers)

    print("Discovery workflow completed. New triggers are ready for review in the discovery_cards table.")

if __name__ == "__main__":
    main()