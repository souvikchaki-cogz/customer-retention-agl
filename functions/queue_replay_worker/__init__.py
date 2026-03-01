import os, json, logging, asyncio
import azure.functions as func
import azure.durable_functions as df
from datetime import datetime, timezone, timedelta
from ..shared import SqlClient

app = func.FunctionApp()

@app.function_name(name="queue_replay_worker")
@app.queue_trigger(arg_name="msg", queue_name=os.getenv("REPLAY_QUEUE_NAME", "event-replay"),
				   connection="AzureWebJobsStorage")
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