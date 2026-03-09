import os
import sys
import json

# Add the parent directory to the path to allow imports from the shared folder
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.azure_openai import get_openai_client
from shared.discovery import generate_triggers

# --- Prerequisites Check ---
def check_env_vars():
    """Checks if the required environment variables are set."""
    required_vars = ["AZURE_OPENAI_API_ENDPOINT", "AZURE_OPENAI_DEPLOYMENTNAME"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print("Error: The following environment variables are not set:", ", ".join(missing_vars))
        print("Please set them in your environment before running this test.")
        sys.exit(1)

    print("✅ Environment variables are set correctly.")

# --- Test Execution ---
if __name__ == "__main__":
    check_env_vars()

    print("\n▶️  Calling Azure OpenAI to generate synthetic triggers for AGL energy churn...")

    try:
        # generate_triggers() uses the shared OpenAI client internally
        new_triggers = generate_triggers()

        print("\n✅ Success! OpenAI returned the following triggers:")
        print(json.dumps(new_triggers, indent=2))

        print("\n--- Test Complete ---")
        if new_triggers:
            print(f"🔥 Result: {len(new_triggers)} new triggers were generated.")
        else:
            print("✔️ Result: No new triggers were generated.")

    except Exception as e:
        import traceback
        print(f"\n❌ An error occurred during the process: {e}")
        print("\n--- Full Traceback ---")
        traceback.print_exc()