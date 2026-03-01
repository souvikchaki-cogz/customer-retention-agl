from ..shared.sql_client import SqlClient
from ..shared.pii import scrub_text
from ..shared.logging_utils import metrics_client

def main(payload: dict) -> dict:
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