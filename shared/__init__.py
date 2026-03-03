# Initialize the shared package

"""This module will serve as the initialization for the shared package."""

from .sql_client import SqlClient
from .azure_openai_predict import get_triggers_via_azure_openai, PROMPT


# --- Lazy wrappers for functions / batch consumers ---
def load_active_ruleset():
    """Lazy proxy – imports shared.rules only when actually called."""
    from .rules import load_active_ruleset as _load
    return _load()


def score_event(ruleset, text_result, features):
    """Lazy proxy – imports shared.rules only when actually called."""
    from .rules import score_event as _score
    return _score(ruleset, text_result, features)


def match_text_rules(text, ruleset):
    """Lazy proxy – imports shared.aoai_text_matcher only when actually called."""
    from .aoai_text_matcher import match_text_rules as _match
    return _match(text, ruleset)


__all__ = [
    "SqlClient",
    "get_triggers_via_azure_openai",
    "PROMPT",
    "load_active_ruleset",
    "score_event",
    "match_text_rules",
]