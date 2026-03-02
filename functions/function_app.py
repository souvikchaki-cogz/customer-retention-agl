import os
import time
import json
import logging
import asyncio
from datetime import datetime
import azure.functions as func
import azure.durable_functions as df
from azure.storage.queue import QueueClient

# Imports relative to the parent directory of 'functions'
from ..shared.rules import load_active_ruleset, score_event
from ..shared.logging_utils import metrics_client
from ..shared.pii import scrub_text
from ..shared.sql_client import SqlClient
from ..shared import match_text_rules
from ..shared.guardrails import enforce_confidence_floors, substring_evidence_guard

# Define the durable function app
app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

# --- Globals and Resource Loading ---
# Load rules once per worker (cold start) to be shared across activities
_RULESET, _RULESET_VERSION = load_active_ruleset()
THRESHOLD = float(os.getenv("LEAD_SCORE_THRESHOLD", "0.7"))
QUEUE_NAME = os.getenv("REPLAY_QUEUE_NAME", "event-replay")
STORAGE_CONN = os.getenv("AzureWebJobsStorage")


# --- Orchestrator ---
# Orchestrator for a single event (customer note / system event)
@app.orchestration_trigger(context_name="context", function_name="orchestrator_event_replay")
def orchestrator_event_replay(context: df.DurableOrchestrationContext):
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


# --- Activity: Call Text Agent ---
@app.activity_trigger(input_name="event", function_name="activity_call_text_agent")
def activity_call_text_agent(event: dict) -> dict:
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


# --- Activity: Evaluate Rules ---
@app.activity_trigger(input_name="payload", function_name="activity_evaluate_rules")
def activity_evaluate_rules(payload: dict) -> dict:
	t0 = time.time()
	text_result = payload["text_result"] # rule_hits from text agent
	features = payload["features"] # structured features
	event = payload["event"]

	# Using pre-loaded ruleset for efficiency
	score, details = score_event(_RULESET, text_result, features)

	should_emit = (score >= THRESHOLD)
	out = {
		"should_emit": should_emit,
		"score": score,
		"rule_hits_json": details["rule_hits_json"],
		"structured_snapshot_json": features,
		"explanation_text": details["explanation_text"],
		"agent_version": details["agent_version"],
		"ruleset_version": _RULESET_VERSION,
		"note_id": event["note_id"],
		"customer_id": features["customer_id"]
	}

	# Observability
	mc = metrics_client()
	mc.track_metric("evaluate_rules_latency_ms", int((time.time()-t0)*1000))
	mc.track_metric("lead_emitted", 1 if should_emit else 0)

	return out


# --- Activity: Write Lead Card ---
@app.activity_trigger(input_name="payload", function_name="activity_write_lead_card")
def activity_write_lead_card(payload: dict) -> dict:
		sql_client = SqlClient()
		sql = """
		INSERT INTO lead_cards (
			customer_id, note_id, score, rule_hits_json, structured_snapshot_json,
			explanation_text, agent_version, ruleset_version, created_ts
		)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, SYSDATETIME())
		"""
		params = [
				payload["customer_id"],
				payload["note_id"],
				payload["score"],
				str(payload["rule_hits_json"]),
				str(payload["structured_snapshot_json"]),
				scrub_text(payload["explanation_text"]),
				payload["agent_version"],
				payload["ruleset_version"]
		]
		sql_client.fetch_one(sql, params) # use fetch_one for execution convenience
		mc = metrics_client()
		mc.track_metric("lead_cards_written", 1)
		return {"ok": True}


# --- Activity: Fetch Structured Features ---
@app.activity_trigger(input_name="payload", function_name="activity_fetch_structured")
def activity_fetch_structured(payload: dict) -> dict:
    customer_id = payload["customer_id"]
    event_ts = payload["event_ts"]

    sqlc = SqlClient()
    sql = """
    ;WITH last_snap AS (
      SELECT TOP (1)
        customer_id, rate AS current_rate, term_months,
        LAG(rate) OVER (PARTITION BY customer_id ORDER BY snapshot_ts) AS prev_rate,
        DATEDIFF(day, origination_date, ?) AS account_age_days
      FROM customers_snapshot
      WHERE customer_id = ?
      ORDER BY snapshot_ts DESC
    )
    SELECT * FROM last_snap;
    """
    row = sqlc.fetch_one(sql, params=[event_ts, customer_id]) or {}

    rate_diff = None
    if row.get("current_rate") is not None and row.get("prev_rate") is not None:
        rate_diff = float(row["current_rate"]) - float(row["prev_rate"])

    return {
        "customer_id": customer_id,
        "current_rate": row.get("current_rate"),
        "prev_rate": row.get("prev_rate"),
        "rate_diff": rate_diff,
        "term_months": row.get("term_months"),
        "account_age_days": row.get("account_age_days"),
    }


# --- HTTP Trigger: Start Replay ---
@app.route(route="replay/start", methods=["POST"])
def http_start_replay(req: func.HttpRequest) -> func.HttpResponse:
		"""
		Body: {
			"from_ts": "2024-01-01T00:00:00Z",
			"to_ts": "2024-01-08T00:00:00Z",
			"accelerate": 60, # 60x (optional)
			"batch_size": 500 # optional
		}
		Enqueues replay instructions for the worker.
		"""
		try:
			body = req.get_json()
			q = QueueClient.from_connection_string(STORAGE_CONN, QUEUE_NAME)
			q.create_queue()
			q.send_message(json.dumps(body))
			return func.HttpResponse("Replay scheduled", status_code=202)
		except Exception as e:
			logging.exception("Failed to schedule replay")
			return func.HttpResponse(str(e), status_code=500)


# --- Queue Trigger: Replay Worker ---
@app.queue_trigger(arg_name="msg", queue_name=QUEUE_NAME, connection="AzureWebJobsStorage")
@app.durable_client_input(client_name="starter")
async def queue_replay_worker(msg: func.QueueMessage, starter: df.DurableOrchestrationClient):
	"""
	Reads historical notes/system_events from Fabric/SQL db in ts order,
	and starts orchestrations at accelerated cadence.
	"""
	payload = json.loads(msg.get_body().decode())
	from_ts = datetime.fromisoformat(payload["from_ts"].replace("Z","+00:00"))
	to_ts = datetime.fromisoformat(payload["to_ts"].replace("Z","+00:00"))
	accelerate = float(payload.get("accelerate", 120)) # speedup factor
	batch_size = int(payload.get("batch_size", 1000))

	sql_client = SqlClient()
	# Query notes; optional JOIN on system_events if you store them similarly
	sql = """
	SELECT customer_id, note_id, created_ts as ts, note_text as text
	FROM notes
	WHERE created_ts >= ? AND created_ts < ?
	ORDER BY created_ts ASC
	"""
	for batch in sql_client.iter_query(sql, params=[from_ts, to_ts], chunksize=batch_size):
		for row in batch:
			# throttle based on accelerated cadence: compute delta vs previous event
			# (for demo simplicity, we just small-sleep to simulate near-real-time)
			await asyncio.sleep(0.02 / accelerate)
			instance_id = await starter.start_new(
				"orchestrator_event_replay", client_input=row
			)
			logging.info(f"Started orchestration {instance_id} for note {row['note_id']}")