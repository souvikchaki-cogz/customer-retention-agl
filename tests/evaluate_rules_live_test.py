import os
import sys
import json

# Add the project root to the system path to allow for absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the functions from the v2 function app
from function_app import activity_call_text_agent as call_text_agent
from function_app import activity_fetch_structured as fetch_structured
from function_app import activity_evaluate_rules as evaluate_rules

# --- Prerequisites Check ---
def check_env_vars():
    """Checks if the required environment variables are set."""
    required_vars = ["AZSQL_SERVER", "AZSQL_DB", "AZSQL_UID", "AZSQL_PWD", "USE_SQL_RULES"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print("Error: The following environment variables are not set:", ", ".join(missing_vars))
        print("Please run the 'export' commands in your terminal before running this test.")
        sys.exit(1)
    
    if os.getenv("USE_SQL_RULES") != "1":
        print("Error: The 'USE_SQL_RULES' environment variable must be set to '1' for this test.")
        sys.exit(1)

    print("✅ Environment variables are set correctly.")

# --- Test Execution ---
if __name__ == "__main__":
    check_env_vars()

    # --- Step 1: Define input and call the Text Agent ---
    # This note should trigger the T3_HOW_TO_CLOSE_LOAN text rule.
    # We are testing with CUST0003, who has an interest-only loan expiring soon.
    # Can use this text for testing: "Hi there, I need to understand the process to close my mortgage with you."
    print("--- Test Scenario: Customer asks to close loan, has IO loan expiring soon ---")
    event = {
        "customer_id": "CUST0003",
        "note_id": "note_test_123",
        "ts": "2025-09-21T10:00:00Z",
        "text": "I cannot make the payment this month, I am struggling."
    }
    print(f"\n▶️  1. Calling Text Agent for customer {event['customer_id']}...")
    text_result = call_text_agent(event)
    print("✅ Success! Text Agent returned:")
    print(text_result)

    # --- Step 2: Call the Fetch Structured activity ---
    print(f"\n▶️  2. Fetching structured data for customer {event['customer_id']}...")
    structured_features = fetch_structured(event)
    print("✅ Success! Structured data returned:")
    print(structured_features)

    # --- Step 3: Call the Evaluate Rules activity ---
    print("\n▶️  3. Evaluating rules...")
    eval_payload = {
        "text_result": text_result,
        "features": structured_features,
        "event": {"note_id": event["note_id"], "ts": event["ts"]}
    }

    try:
        final_result = evaluate_rules(eval_payload)
        print("\n✅ Success! Rule evaluation returned:")
        # Pretty-print the JSON output
        print(json.dumps(final_result, indent=2))

        print("\n--- Test Complete ---")
        if final_result.get("should_emit"):
            print(f"🔥 Result: A lead card SHOULD BE EMITTED with a score of {final_result.get('score'):.2f}.")
        else:
            print(f"✔️ Result: A lead card should NOT be emitted with a score of {final_result.get('score'):.2f}.")

    except Exception as e:
        print(f"\n❌ An error occurred during rule evaluation: {e}")