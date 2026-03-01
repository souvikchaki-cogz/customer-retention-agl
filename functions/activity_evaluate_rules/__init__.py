import os, time
from datetime import datetime, timezone
from ..shared.rules import load_active_ruleset, score_event
from ..shared.logging_utils import metrics_client
from ..shared.pii import scrub_text

THRESHOLD = float(os.getenv("LEAD_SCORE_THRESHOLD", "0.7"))

def main(payload: dict) -> dict:
	t0 = time.time()
	text_result = payload["text_result"] # rule_hits from text agent
	features = payload["features"] # structured features
	event = payload["event"]

	ruleset = load_active_ruleset()
	score, details = score_event(ruleset, text_result, features)

	should_emit = (score >= THRESHOLD)
	out = {
		"should_emit": should_emit,
		"score": score,
		"rule_hits_json": details["rule_hits_json"],
		"structured_snapshot_json": features,
		"explanation_text": details["explanation_text"],
		"agent_version": details["agent_version"],
		"ruleset_version": ruleset["version"],
		"note_id": event["note_id"],
		"customer_id": features["customer_id"]
	}

	# Observability
	mc = metrics_client()
	mc.track_metric("evaluate_rules_latency_ms", int((time.time()-t0)*1000))
	mc.track_metric("lead_emitted", 1 if should_emit else 0)

	return out