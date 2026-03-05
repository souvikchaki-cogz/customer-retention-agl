import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from function_app import activity_call_text_agent as call_text_agent
from function_app import activity_fetch_structured as fetch_structured
from function_app import activity_evaluate_rules as evaluate_rules

def check_env_vars():
    required_vars = ["AZSQL_SERVER", "AZSQL_DB", "USE_SQL_RULES"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print("Error: The following environment variables are not set:", ", ".join(missing_vars))
        print("Please set the required environment variables before running this test.")
        sys.exit(1)
    if os.getenv("USE_SQL_RULES") != "1":
        print("Error: USE_SQL_RULES must be set to '1' for this test.")
        sys.exit(1)
    print("✅ Environment variables are set correctly.")

if __name__ == "__main__":
    check_env_vars()

    # --- Test Scenario: Customer compares retailers, property recently listed for sale ---
    # This note should trigger T7_COMPARING_RETAILERS.
    # CUST0001 is assumed to have property_listing_status='FOR_SALE' in agl_structured.
    # Alternative test texts:
    #   "I need a final meter read. We're selling the property next week."  -> T1 + T2
    #   "My bill has doubled this quarter and I'm shocked by the amount."   -> T6
    #   "I can't afford to keep paying this. I need a payment plan."        -> T10 + vulnerability
    print("--- Test Scenario: Customer comparing retailers, property for sale ---")
    event = {
        "customer_id": "CUST0001",
        "note_id": "note_agl_live_001",
        "ts": "2026-03-05T10:00:00Z",
        "text": "I've been shopping around and found a cheaper plan with another retailer. How do I switch?"
    }
    print(f"\n▶️  1. Calling Text Agent for customer {event['customer_id']}...")
    text_result = call_text_agent(event)
    print("✅ Success! Text Agent returned:")
    print(text_result)

    print(f"\n▶️  2. Fetching structured data for customer {event['customer_id']}...")
    structured_features = fetch_structured(event)
    print("✅ Success! Structured data returned:")
    print(structured_features)

    print("\n▶️  3. Evaluating rules...")
    eval_payload = {
        "text_result": text_result,
        "features": structured_features,
        "event": {"note_id": event["note_id"], "ts": event["ts"]}
    }

    try:
        final_result = evaluate_rules(eval_payload)
        print("\n✅ Success! Rule evaluation returned:")
        print(json.dumps(final_result, indent=2))
        print("\n--- Test Complete ---")
        if final_result.get("should_emit"):
            print(f"🔥 Result: A lead card SHOULD BE EMITTED with a score of {final_result.get('score'):.2f}.")
        else:
            print(f"✔️ Result: A lead card should NOT be emitted with a score of {final_result.get('score'):.2f}.")
    except Exception as e:
        print(f"\n❌ An error occurred during rule evaluation: {e}")