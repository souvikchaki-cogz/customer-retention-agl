# Initialize the shared package

"""This module will serve as the initialization for the shared package."""

from .sql_client import SqlClient
from .discovery import generate_triggers, PROMPT


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
    """Lazy proxy – imports shared.text_matcher only when actually called."""
    from .text_matcher import match_text_rules as _match
    return _match(text, ruleset)


__all__ = [
    "SqlClient",
    "generate_triggers",
    "PROMPT",
    "load_active_ruleset",
    "score_event",
    "match_text_rules",
]