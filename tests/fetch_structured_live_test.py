import os
import sys

# Add the project root to the system path to allow for absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from function_app import activity_fetch_structured as fetch_structured

# --- Prerequisites Check ---
def check_env_vars():
    """Checks if the required database environment variables are set."""
    required_vars = ["AZSQL_SERVER", "AZSQL_DB"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print("Error: The following environment variables are not set:", ", ".join(missing_vars))
        print("Please set the required environment variables before running this test.")
        sys.exit(1)
    print("✅ Environment variables are set.")

# --- Test Execution ---
if __name__ == "__main__":
    check_env_vars()

    # Define the customer you want to test with.
    # This customer_id MUST exist in your dbo.Structured table.
    test_customer_id = "CUST0003"
    payload = {"customer_id": test_customer_id}

    print(f"\n▶️  Attempting to fetch structured data for customer: {test_customer_id}...")

    try:
        # Call the function, which will attempt a live database connection
        result = fetch_structured(payload)

        print("\n✅ Success! Function returned:")
        print(result)

    except Exception as e:
        print(f"\n❌ An error occurred during the function call: {e}")
        print("   Please check your database credentials, firewall rules, and network connection.")