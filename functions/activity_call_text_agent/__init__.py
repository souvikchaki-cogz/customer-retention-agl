import os, logging
import azure.functions as func
from ..shared.aoai_text_matcher import match_text_rules
from ..shared.guardrails import enforce_confidence_floors, substring_evidence_guard
from ..shared.pii import scrub_text
from ..shared.rules import load_active_ruleset

# --- load rules once per worker (cold start)
_RULESET, _RULESET_VERSION = load_active_ruleset() # returns (dict, "version")

def main(event: dict) -> dict:
    """
    Input event: {customer_id, note_id, ts, text}
    Output: {"rule_hits":[{rule_id, confidence, evidence_text}], model_latency_ms, llm_used}
    """
    note_text = scrub_text(event.get("text", ""))

    # now pass ruleset so LLM knows the allowed IDs
    res = match_text_rules(note_text, _RULESET)

    # local guards
    res["rule_hits"] = [
        h for h in res["rule_hits"]
        if substring_evidence_guard(h.get("evidence_text"))
    ]
    res["rule_hits"] = enforce_confidence_floors(res["rule_hits"])
    res["ruleset_version"] = _RULESET_VERSION
    return res