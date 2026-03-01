import azure.functions as func
import azure.durable_functions as df
from datetime import datetime

# Orchestrator for a single event (customer note / system event)
def orchestrator_fn(context: df.DurableOrchestrationContext):
	event = context.get_input() # dict: {customer_id, note_id, ts, text, system_events?}
	# Step 1: text-trigger detection (Azure OpenAI wrapper)
	text_res = yield context.call_activity('activity_call_text_agent', event)

	# Step 2: fetch structured features from Fabric (rate diff, term, etc.)
	features = yield context.call_activity('activity_fetch_structured', {
		"customer_id": event["customer_id"],
		"event_ts": event["ts"]
	})

	# Step 3: evaluate deterministic rules (combining text + structured + weights/decay)
	eval_result = yield context.call_activity('activity_evaluate_rules', {
		"text_result": text_res,
		"features": features,
		"event": {"note_id": event["note_id"], "ts": event["ts"]}
	})

	# Step 4: write lead card if threshold hit
	if eval_result.get("should_emit", False):
		_ = yield context.call_activity('activity_write_lead_card', eval_result)

	return {"processed": True, "lead_emitted": eval_result.get("should_emit", False)}

main = df.Orchestrator.create(orchestrator_fn)