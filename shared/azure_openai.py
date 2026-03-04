import os
import logging
from typing import Optional

from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

logger = logging.getLogger(__name__)

_client: Optional[AzureOpenAI] = None


def get_openai_client() -> AzureOpenAI:
    """
    Initializes and returns a singleton AzureOpenAI client.
    It supports both API key and Azure AD authentication.
    """
    global _client
    if _client:
        return _client

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")

    if not endpoint or not deployment:
        raise ValueError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT must be set.")

    try:
        if api_key:
            logging.info("Initializing AzureOpenAI client with API key.")
            _client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=api_version,
            )
        else:
            logging.info("Initializing AzureOpenAI client with Azure AD token.")
            token_provider = get_bearer_token_provider(DefaultAzureCredential(),
                                                       "https://cognitiveservices.azure.com/.default")
            _client = AzureOpenAI(
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider,
                api_version=api_version,
            )
        return _client
    except Exception as e:
        logging.critical("Failed to initialize AzureOpenAI client: %s", e)
        raise