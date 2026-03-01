# Initialize the shared package

"""This module will serve as the initialization for the shared package."""

from .sql_client import SqlClient
from .rules import load_active_ruleset, score_event
from .azure_openai_predict import get_triggers_via_azure_openai, PROMPT
from .aoai_text_matcher import match_text_rules

__all__ = [
    "SqlClient",
    "load_active_ruleset",
    "score_event",
    "get_triggers_via_azure_openai",
    "PROMPT",
    "match_text_rules",
]
