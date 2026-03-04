import os
import json
from shared.discovery import generate_triggers
from dotenv import load_dotenv

# This script is for manually triggering the Azure OpenAI call to inspect the response.
#
# Before running, ensure you have a .env file in the project root, or that
# the following environment variables are set in your shell:
# - AZURE_OPENAI_ENDPOINT
# - AZURE_OPENAI_API_KEY
# - AZURE_OPENAI_DEPLOYMENT
#
# To run the script, execute this command from the project root directory:
# python run_openai_call.py

def main():
    """
    Loads environment variables, calls the Azure OpenAI function,
    and prints the response.
    """
    # Load environment variables from .env file
    load_dotenv()

    print("Attempting to call Azure OpenAI...")

    # Check if variables are set
    if not all([
        os.getenv("AZURE_OPENAI_ENDPOINT"),
        os.getenv("AZURE_OPENAI_API_KEY"),
        os.getenv("AZURE_OPENAI_DEPLOYMENT"),
    ]):
        print("\n---")
        print("ERROR: Azure OpenAI environment variables are not set.")
        print("Please create a .env file or set them in your environment.")
        print("Falling back to the static example data.")
        print("---\n")

    try:
        # Call the function
        triggers = generate_triggers()

        # Print the response in a readable format
        print("\n--- Azure OpenAI Response ---")
        print(json.dumps(triggers, indent=2))
        print("-----------------------------\n")

    except Exception as e:
        print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    main()