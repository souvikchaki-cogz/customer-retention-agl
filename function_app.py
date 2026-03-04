"""Azure Functions App in Python v2 programming model."""
import logging
import time
import random
from datetime import datetime, timezone, date

import azure.functions as func
import azure.durable_functions as df

from shared.text_matcher import match_text_rules
from shared.guardrails import detect_vulnerability
from shared.pii import scrub_text
from shared.rules import load_active_ruleset, score_event
from shared.sql_client import SqlClient
from shared.config import LEAD_SCORE_THRESHOLD, LOG_LEVEL  # <--- unified config import

# --- Set logging config from shared LOG_LEVEL ---
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)
logger.debug("Configured function logging with level %s", LOG_LEVEL)

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

THRESHOLD = LEAD_SCORE_THRESHOLD  # <--- from shared config

@app.route(route="http_start_single_analysis")
@app.durable_client_input(client_name="durable_client")
async def http_start_single_analysis(req: func.HttpRequest, durable_client: df.DurableOrchestrationClient) -> func.HttpResponse:
    """
    HTTP Trigger to start a single analysis for the interactive demo UI.
    Expects a JSON body with 'customer_id' and 'text'.
    """
    logger.info("HTTP trigger received request for single analysis.")

    try:
        body = req.get_json()
        customer_id = body.get("customer_id")
        note_text = body.get("text")
        if not customer_id or not note_text:
            logger.warning("Request body missing 'customer_id' or 'text'.")
            return func.HttpResponse(
                "Please provide 'customer_id' and 'text' in the request body.",
                status_code=400
            )
    except ValueError:
        logger.error("Invalid JSON format in request body.")
        return func.HttpResponse(
            "Invalid JSON format in request body.",
            status_code=400
        )

    logger.info("Received single analysis request for customer_id: %s.", customer_id)

    event = {
        "customer_id": customer_id,
        "note_id": f"demo_{datetime.now(timezone.utc).isoformat()}",
        "ts": datetime.now(timezone.utc).isoformat(),
        "text": note_text
    }

    try:
        instance_id = await durable_client.start_new("orchestrator_event_replay", client_input=event)
        logger.info("Started orchestration with ID = '%s'.", instance_id)
        return durable_client.create_check_status_response(req, instance_id)
    except Exception as e:
        logger.error("Error starting orchestration: %s", str(e))
        return func.HttpResponse(
            "Failed to start analysis orchestration.",
            status_code=500
        )

@app.orchestration_trigger(context_name="context")
def orchestrator_event_replay(context: df.DurableOrchestrationContext):
    event = context.get_input()
    logger.info("Orchestration started for customer_id: %s", event.get('customer_id'))

    try:
        context.set_custom_status({"status": "Analyzing note with AI Text Agent...", "progress": 25})
        logger.info("Calling activity: activity_call_text_agent")
        text_res = yield context.call_activity('activity_call_text_agent', event)

        if text_res.get("vulnerability_detected"):
            keywords = text_res.get("vulnerability_keywords", [])
            logger.warning("VULNERABILITY GUARDRAIL TRIGGERED. Terminating orchestration for customer %s. Keywords: %s", event.get('customer_id'), keywords)
            final_status = {"status": "Done. Orchestration terminated due to detected customer vulnerability.", "progress": 100, "result": dict()}
            context.set_custom_status(final_status)
            return {"processed": True, "lead_emitted": False, "reason": "vulnerability_suppressed"}

        rule_hits = text_res.get("rule_hits", [])
        trigger_names = [h.get('rule_id') for h in rule_hits if h.get('rule_id')]
        status_detail = "Found triggers: %s" % ', '.join(trigger_names) if trigger_names else "No specific text triggers found."
        logger.info("activity_call_text_agent completed. %s", status_detail)

        context.set_custom_status({"status": "Fetching customer snapshot...", "progress": 50, "detail": status_detail})
        logger.info("Calling activity: activity_fetch_structured")
        features = yield context.call_activity('activity_fetch_structured', {
            "customer_id": event["customer_id"],
            "event_ts": event["ts"]
        })
        logger.info("activity_fetch_structured completed.")

        context.set_custom_status({"status": "Evaluating rules and calculating score...", "progress": 75, "detail": status_detail})
        logger.info("Calling activity: activity_evaluate_rules")
        eval_result = yield context.call_activity('activity_evaluate_rules', {
            "text_result": text_res,
            "features": features,
            "event": {"note_id": event["note_id"], "ts": event["ts"]}
        })
        logger.info("activity_evaluate_rules completed.")

        if eval_result.get("should_emit", False):
            final_score = round(eval_result.get("score", 0) * 100)
            context.set_custom_status({"status": f"Score ({final_score}) exceeds threshold. Generating lead...", "progress": 90, "detail": status_detail})
            logger.info("Calling activity: activity_write_lead_card")
            _ = yield context.call_activity('activity_write_lead_card', eval_result)
            final_status = {"status": "Done. Lead Card has been generated.", "progress": 100, "result": eval_result}
            logger.info("activity_write_lead_card completed.")
        else:
            final_score = round(eval_result.get("score", 0) * 100)
            final_status = {"status": f"Done. Score ({final_score}) is below threshold. No lead generated.", "progress": 100, "result": eval_result}

        logger.info("Orchestration completed successfully.")
        context.set_custom_status(final_status)
        return {"processed": True, "lead_emitted": eval_result.get("should_emit", False)}

    except Exception as e:
        logger.error("Orchestration failed with error: %s", e)
        context.set_custom_status({"status": "Orchestration failed.", "error": str(e)})
        raise

@app.activity_trigger(input_name="payload")
def activity_call_text_agent(payload: dict) -> dict:
    """
    Input payload: {customer_id, note_id, ts, text}
    Output: {"rule_hits":[{rule_id, confidence, evidence_text}], model_latency_ms, llm_used}
    """
    logger.info("activity_call_text_agent started.")
    customer_id = payload.get("customer_id")
    try:
        logger.info("Calling text agent for customer_id: %s", customer_id)
        note_text = scrub_text(payload.get("text", ""))

        is_vulnerable, vulnerability_keywords = detect_vulnerability(note_text)
        ruleset, ruleset_version = load_active_ruleset()

        if not ruleset or ruleset_version == "error":
            logger.error("Cannot process text agent: Ruleset is not loaded.")
            return {"rule_hits": [], "error": "Ruleset not loaded."}

        res = match_text_rules(note_text, ruleset)
        res["vulnerability_detected"] = is_vulnerable
        res["vulnerability_keywords"] = vulnerability_keywords
        res["ruleset_version"] = ruleset_version
        return res

    except Exception as e:
        logger.error("An error occurred in activity_call_text_agent for customer_id %s: %s", customer_id, e)
        raise

@app.activity_trigger(input_name="payload")
def activity_evaluate_rules(payload: dict) -> dict:
    logger.info("activity_evaluate_rules started.")
    try:
        t0 = time.time()
        text_result = payload["text_result"]
        features = payload["features"]
        event = payload["event"]
        customer_id = features.get("customer_id")

        logger.info("Evaluating rules for customer_id: %s", customer_id)

        ruleset, ruleset_version = load_active_ruleset()
        score, details = score_event(ruleset, text_result, features)

        serializable_features = features.copy()
        for key, value in serializable_features.items():
            if isinstance(value, (datetime, date)):
                serializable_features[key] = value.isoformat()

        should_emit = (score >= THRESHOLD)
        logger.info(
            "Rule evaluation completed for customer_id: %s. Score: %s, Threshold: %s, Emit: %s",
            customer_id, score, THRESHOLD, should_emit
        )
        logger.info("Metric: lead_score=%s", score)
        logger.info("Metric: lead_emitted=%d", 1 if should_emit else 0)

        out = {
            "should_emit": should_emit,
            "score": score,
            "rule_hits_json": details["rule_hits_json"],
            "structured_snapshot_json": serializable_features,
            "explanation_text": details["explanation_text"],
            "agent_version": details["agent_version"],
            "ruleset_version": ruleset_version,
            "note_id": event["note_id"],
            "customer_id": customer_id
        }

        latency = (time.time() - t0) * 1000
        logger.info("activity_evaluate_rules completed in %.2f ms.", latency)
        return out

    except KeyError as ke:
        logger.error("Missing key in payload for activity_evaluate_rules: %s", ke)
        raise
    except Exception as e:
        logger.error("An error occurred in activity_evaluate_rules: %s", e)
        raise

@app.activity_trigger(input_name="payload")
def activity_fetch_structured(payload: dict) -> dict:
    logger.info("activity_fetch_structured started.")
    customer_id = payload.get("customer_id")
    if not customer_id:
        logger.error("No customer_id provided in payload. Failing activity.")
        raise ValueError("No customer_id provided in payload.")

    try:
        logger.info("Fetching structured data for customer_id: %s", customer_id)
        sqlc = SqlClient()

        customer_sql = '''
            SELECT TOP 1 * FROM dbo.Structured WHERE customer_id = ?
        '''
        customer_data = sqlc.fetch_one(customer_sql, params=[customer_id])

        if not customer_data:
            logger.warning("No structured data found for customer_id: %s", customer_id)
            return {"customer_id": customer_id, "error": "No structured data found."}

        product_name = customer_data.get("product_name")
        advertised_rate = None

        if product_name:
            rates_sql = "SELECT advertised_rate FROM dbo.product_rates WHERE product_name = ?"
            rate_data = sqlc.fetch_one(rates_sql, params=[product_name])
            if rate_data:
                advertised_rate = rate_data.get("advertised_rate")

        if not advertised_rate:
            logger.warning("No matching advertised rate found for product: '%s'.", product_name)

        customer_data['advertised_rate'] = advertised_rate

        for key, value in customer_data.items():
            if isinstance(value, (datetime, date)):
                customer_data[key] = value.isoformat()

        logger.info("activity_fetch_structured completed successfully.")
        customer_data["loan_tenure"] = random.randint(0, 9)
        return customer_data

    except Exception as e:
        logger.error("An error occurred in activity_fetch_structured for customer_id %s: %s", customer_id, e)
        raise

@app.activity_trigger(input_name="payload")
def activity_write_lead_card(payload: dict) -> dict:
    logger.info("activity_write_lead_card started.")
    customer_id = payload.get("customer_id")
    try:
        logger.info("Writing lead card for customer_id: %s", customer_id)
        sql_client = SqlClient()
        sql = '''
        INSERT INTO lead_cards (
            customer_id, note_id, score, rule_hits_json, structured_snapshot_json,
            explanation_text, agent_version, ruleset_version, created_ts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, SYSDATETIME())
        '''
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
        sql_client.fetch_one(sql, params)
        logger.info("Successfully wrote lead card for customer_id: %s", customer_id)
        return {"ok": True}
    except KeyError as ke:
        logger.error("Missing key in payload for activity_write_lead_card: %s", ke)
        raise
    except Exception as e:
        logger.error("An error occurred in activity_write_lead_card for customer_id %s: %s", customer_id, e)
        raise