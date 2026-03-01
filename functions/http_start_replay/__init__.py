import os, json, logging
import azure.functions as func
from azure.storage.queue import QueueClient

QUEUE_NAME = os.getenv("REPLAY_QUEUE_NAME", "event-replay")
STORAGE_CONN = os.getenv("AzureWebJobsStorage")

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

@app.function_name(name="http_start_replay")
@app.route(route="replay/start", methods=["POST"])
def start_replay(req: func.HttpRequest) -> func.HttpResponse:
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