import os
import json
from dotenv import load_dotenv

from shared.discovery import generate_triggers

# This script is for manually triggering the Azure OpenAI call to inspect the response.
#
# Before running, ensure you have a .env file in the project root, or that
# the following environment variables are set in your shell:
# - AZURE_OPENAI_ENDPOINT
# - AZURE_OPENAI_API_KEY
# - AZURE_OPENAI_DEPLOYMENTNAME
#
# To run the script, execute this command from the project root directory:
#   python run_openai_call.py


_REQUIRED_ENV_VARS = [
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENTNAME",
]


def check_env() -> bool:
    """Warns if any required Azure OpenAI env vars are missing. Returns True if all are set."""
    missing = [v for v in _REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        print("\n---")
        print("ERROR: The following Azure OpenAI environment variables are not set:")
        for var in missing:
            print(f"  - {var}")
        print("Please create a .env file or set them in your environment.")
        print("Falling back to the static example data.")
        print("---\n")
        return False
    return True


def main():
    """
    Loads environment variables, calls the Azure OpenAI function,
    and prints the response.
    """
    load_dotenv()
    print("Attempting to call Azure OpenAI...")
    check_env()

    try:
        triggers = generate_triggers()
        print("\n--- Azure OpenAI Response ---")
        print(json.dumps(triggers, indent=2))
        print("-----------------------------\n")
    except Exception as e:
        print(f"\nAn error occurred: {e}")


if __name__ == "__main__":
    main()