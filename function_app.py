"""Azure Durable Functions App — AGL Energy Customer Churn Retention System."""
import logging
import time
from datetime import datetime, timezone, date

import azure.functions as func
import azure.durable_functions as df

from shared.text_matcher import match_text_rules
from shared.guardrails import detect_vulnerability, detect_life_support
from shared.pii import scrub_text
from shared.rules import load_active_ruleset, score_event
from shared.sql_client import SqlClient
from shared.config import LEAD_SCORE_THRESHOLD, LOG_LEVEL

# Import shared models
from shared.models import (
    EvaluateRequest, EvaluateResponse,
    PredictResponse, TriggerStat,
    ExistingTrigger, ExistingTriggersResponse,
    ApproveTriggerRequest, ApproveTriggerResponse,
    DeleteTriggerResponse
)

# --- Logging ---
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)
logger.debug("Configured function logging with level %s", LOG_LEVEL)

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

THRESHOLD = LEAD_SCORE_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# HTTP TRIGGER — Entry point for the interactive demo UI
# ─────────────────────────────────────────────────────────────────────────────

@app.route(route="http_start_single_analysis")
@app.durable_client_input(client_name="durable_client")
async def http_start_single_analysis(
    req: func.HttpRequest,
    durable_client: df.DurableOrchestrationClient
) -> func.HttpResponse:
    """
    HTTP Trigger to start a single churn analysis for the interactive demo UI.
    Expects a JSON body: { "customer_id": "...", "note": "..." }
    """
    logger.info("HTTP trigger received request for single analysis.")

    body = None
    try:
        body = req.get_json()
        eval_req = EvaluateRequest(**body)
        customer_id = eval_req.customer_id
        note_text = eval_req.note
    except Exception as e:
        logger.error("Invalid request format: %s", str(e))
        cid = "unknown"
        if isinstance(body, dict):
            cid = body.get("customer_id", "unknown")
        err_resp = EvaluateResponse(
            message="Please provide 'customer_id' and 'note' in the request body.",
            customer_id=cid,
            status="error"
        )
        return func.HttpResponse(
            err_resp.json(),
            mimetype="application/json",
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
        instance_id = await durable_client.start_new(
            "orchestrator_event_replay", client_input=event
        )
        logger.info("Started orchestration with ID = '%s'.", instance_id)
        return durable_client.create_check_status_response(req, instance_id)
    except Exception as e:
        logger.error("Error starting orchestration: %s", str(e))
        err_resp = EvaluateResponse(
            message="Failed to start analysis orchestration.",
            customer_id=customer_id,
            instance_id=None,
            status="error"
        )
        return func.HttpResponse(
            err_resp.json(),
            mimetype="application/json",
            status_code=500
        )


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

@app.orchestration_trigger(context_name="context")
def orchestrator_event_replay(context: df.DurableOrchestrationContext):
    """
    Durable Functions orchestrator.

    Pipeline:
        1. activity_call_text_agent   — PII scrub → vulnerability check → LLM text rule matching
        2. activity_fetch_structured  — Fetch AGL account features from SQL (tariff, bills, property signal)
        3. activity_evaluate_rules    — Combine text + structured signals → churn score
        4. activity_write_lead_card   — Persist lead card to DB (if score ≥ threshold)

    Suppression gates (short-circuit before scoring):
        - Vulnerability guardrail: financial hardship / distress keywords
        - Life support / hardship program: AER-protected customers — NEVER emit a lead
        - Protected customer flag: set in activity_fetch_structured
    """
    event = context.get_input()
    logger.info("Orchestration started for customer_id: %s", event.get("customer_id"))

    try:
        # ── STEP 1: Text Agent ────────────────────────────────────────────────
        context.set_custom_status({"status": "Analysing customer note with AI Text Agent...", "progress": 25})
        logger.info("Calling activity: activity_call_text_agent")
        text_res = yield context.call_activity("activity_call_text_agent", event)

        # Vulnerability guardrail — suppress lead for distressed customers
        if text_res.get("vulnerability_detected"):
            keywords = text_res.get("vulnerability_keywords", [])
            logger.warning(
                "VULNERABILITY GUARDRAIL TRIGGERED. Terminating orchestration for customer %s. Keywords: %s",
                event.get("customer_id"), keywords
            )
            final_status = {
                "status": "Done. Orchestration terminated — customer vulnerability detected. No lead generated.",
                "progress": 100,
                "result": {}
            }
            context.set_custom_status(final_status)
            return {"processed": True, "lead_emitted": False, "reason": "vulnerability_suppressed"}

        rule_hits = text_res.get("rule_hits", [])
        trigger_names = [h.get("rule_id") for h in rule_hits if h.get("rule_id")]
        status_detail = (
            "Found triggers: %s" % ", ".join(trigger_names)
            if trigger_names
            else "No specific text triggers found."
        )
        logger.info("activity_call_text_agent completed. %s", status_detail)

        # ── STEP 2: Fetch Structured Data ─────────────────────────────────────
        context.set_custom_status({
            "status": "Fetching AGL account snapshot...",
            "progress": 50,
            "detail": status_detail
        })
        logger.info("Calling activity: activity_fetch_structured")
        features = yield context.call_activity("activity_fetch_structured", {
            "customer_id": event["customer_id"],
            "event_ts": event["ts"]
        })
        logger.info("activity_fetch_structured completed.")

        # Protected customer gate — life support or active hardship program
        # (AER-regulated: these customers must NEVER be targeted for retention sales)
        if features.get("_suppress_lead"):
            suppress_reason = features.get("_suppress_reason", "protected_customer")
            logger.warning(
                "PROTECTED CUSTOMER GUARDRAIL: Suppressing lead for customer %s. Reason: %s",
                event.get("customer_id"), suppress_reason
            )
            final_status = {
                "status": f"Done. Lead suppressed — {suppress_reason.replace('_', ' ')} (AER protected).",
                "progress": 100,
                "result": {}
            }
            context.set_custom_status(final_status)
            return {"processed": True, "lead_emitted": False, "reason": suppress_reason}

        # ── STEP 3: Evaluate Rules & Score ────────────────────────────────────
        context.set_custom_status({
            "status": "Evaluating churn signals and calculating score...",
            "progress": 75,
            "detail": status_detail
        })
        logger.info("Calling activity: activity_evaluate_rules")
        eval_result = yield context.call_activity("activity_evaluate_rules", {
            "text_result": text_res,
            "features": features,
            "event": {"note_id": event["note_id"], "ts": event["ts"]}
        })
        logger.info("activity_evaluate_rules completed.")

        # ── STEP 4: Write Lead Card (if score exceeds threshold) ──────────────
        if eval_result.get("should_emit", False):
            final_score = round(eval_result.get("score", 0) * 100)
            context.set_custom_status({
                "status": f"Score ({final_score}) exceeds threshold. Generating retention lead...",
                "progress": 90,
                "detail": status_detail
            })
            logger.info("Calling activity: activity_write_lead_card")
            _ = yield context.call_activity("activity_write_lead_card", eval_result)
            final_status = {
                "status": "Done. Retention Lead Card has been generated.",
                "progress": 100,
                "result": eval_result
            }
            logger.info("activity_write_lead_card completed.")
        else:
            final_score = round(eval_result.get("score", 0) * 100)
            final_status = {
                "status": f"Done. Score ({final_score}) is below threshold. No lead generated.",
                "progress": 100,
                "result": eval_result
            }

        logger.info("Orchestration completed successfully.")
        context.set_custom_status(final_status)
        return {"processed": True, "lead_emitted": eval_result.get("should_emit", False)}

    except Exception as e:
        logger.error("Orchestration failed with error: %s", e)
        context.set_custom_status({"status": "Orchestration failed.", "error": str(e)})
        raise


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY: Text Agent
# ─────────────────────────────────────────────────────────────────────────────

@app.activity_trigger(input_name="payload")
def activity_call_text_agent(payload: dict) -> dict:
    """
    Scrubs PII from the customer note, runs the vulnerability guardrail,
    then calls Azure OpenAI to match the note against the active churn rule catalogue.

    Input:  { customer_id, note_id, ts, text }
    Output: { rule_hits: [...], vulnerability_detected: bool,
              vulnerability_keywords: [...], ruleset_version: str }
    """
    logger.info("activity_call_text_agent started.")
    customer_id = payload.get("customer_id")
    try:
        logger.info("Calling text agent for customer_id: %s", customer_id)
        note_text = scrub_text(payload.get("text", ""))

        # Vulnerability guardrail (financial hardship, health, cognitive)
        is_vulnerable, vulnerability_keywords = detect_vulnerability(note_text)

        # Life support guardrail (AER-protected class — checked at text level as an
        # early exit, also enforced at the structured data level in activity_fetch_structured)
        if not is_vulnerable:
            is_life_support = detect_life_support(note_text)
            if is_life_support:
                is_vulnerable = True
                vulnerability_keywords = ["life_support"]

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
        logger.error(
            "An error occurred in activity_call_text_agent for customer_id %s: %s",
            customer_id, e
        )
        raise


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY: Fetch Structured Data
# ─────────────────────────────────────────────────────────────────────────────

@app.activity_trigger(input_name="payload")
def activity_fetch_structured(payload: dict) -> dict:
    """
    Fetches AGL account structured features from dbo.agl_structured for the given
    customer_id, then enriches with tariff rate data from dbo.agl_tariff_rates.

    AGL-specific structured signals returned:
        tariff_name, contract_type, contract_end_date
        last_bill_amount, prev_bill_amount
        conditional_discount_removed
        property_listing_status, property_listing_date  ← proactive property market signal
        is_life_support, is_hardship                    ← AER-protected class flags
        fuel_type, service_address
        usage_rate_kwh, supply_charge, feed_in_tariff   ← enriched from agl_tariff_rates

    Suppression logic:
        Sets _suppress_lead = True and _suppress_reason for any customer where
        is_life_support = 1 or is_hardship = 1.
        The orchestrator checks this flag and short-circuits before scoring.

    Input:  { customer_id, event_ts }
    Output: dict of customer features (all date/datetime fields serialised to ISO strings)
    """
    logger.info("activity_fetch_structured started.")
    customer_id = payload.get("customer_id")
    if not customer_id:
        logger.error("No customer_id provided in payload. Failing activity.")
        raise ValueError("No customer_id provided in payload.")

    try:
        logger.info("Fetching structured data for customer_id: %s", customer_id)
        sqlc = SqlClient()

        # Fetch core account record from agl_structured
        customer_sql = "SELECT TOP 1 * FROM dbo.agl_structured WHERE customer_id = ?"
        customer_data = sqlc.fetch_one(customer_sql, params=[customer_id])

        if not customer_data:
            logger.warning("No structured data found for customer_id: %s", customer_id)
            return {"customer_id": customer_id, "error": "No structured data found."}

        # ── AER Protected Customer Gate ───────────────────────────────────────
        # Under AER rules and AGL's hardship policy, life support customers and
        # customers on a hardship program must NEVER be targeted for retention sales.
        # Setting _suppress_lead = True causes the orchestrator to short-circuit
        # before the scoring and lead-card steps, regardless of churn signals.
        if customer_data.get("is_life_support"):
            logger.warning(
                "Life support customer detected for customer_id: %s. Suppressing lead.",
                customer_id
            )
            customer_data["_suppress_lead"] = True
            customer_data["_suppress_reason"] = "life_support_customer"

        elif customer_data.get("is_hardship"):
            logger.warning(
                "Hardship program customer detected for customer_id: %s. Suppressing lead.",
                customer_id
            )
            customer_data["_suppress_lead"] = True
            customer_data["_suppress_reason"] = "hardship_program_customer"

        # ── Tariff Rate Enrichment ────────────────────────────────────────────
        # Looks up the advertised tariff rates for the customer's current product.
        # usage_rate_kwh and supply_charge are used by the scoring engine to compute
        # the effective bill rate for comparison purposes.
        tariff_name = customer_data.get("tariff_name")
        if tariff_name:
            tariff_sql = (
                "SELECT usage_rate_kwh, supply_charge, feed_in_tariff "
                "FROM dbo.agl_tariff_rates WHERE tariff_name = ?"
            )
            tariff_data = sqlc.fetch_one(tariff_sql, params=[tariff_name])
            if tariff_data:
                customer_data["usage_rate_kwh"] = tariff_data.get("usage_rate_kwh")
                customer_data["supply_charge"]   = tariff_data.get("supply_charge")
                customer_data["feed_in_tariff"]  = tariff_data.get("feed_in_tariff")
                logger.info(
                    "Enriched customer_id %s with tariff rates for '%s' "
                    "(usage=%.4f $/kWh, supply=%.4f $/day).",
                    customer_id, tariff_name,
                    tariff_data.get("usage_rate_kwh", 0),
                    tariff_data.get("supply_charge", 0),
                )
            else:
                logger.warning(
                    "No tariff rates found in agl_tariff_rates for tariff_name: '%s'.",
                    tariff_name
                )
                customer_data["usage_rate_kwh"] = None
                customer_data["supply_charge"]   = None
                customer_data["feed_in_tariff"]  = None
        else:
            logger.warning(
                "No tariff_name on record for customer_id: %s. Cannot enrich rates.",
                customer_id
            )

        # ── Serialise date / datetime fields to ISO strings ───────────────────
        # Azure Durable Functions requires all activity outputs to be JSON-serialisable.
        for key, value in customer_data.items():
            if isinstance(value, (datetime, date)):
                customer_data[key] = value.isoformat()

        logger.info(
            "activity_fetch_structured completed successfully for customer_id: %s.", customer_id
        )
        return customer_data

    except Exception as e:
        logger.error(
            "An error occurred in activity_fetch_structured for customer_id %s: %s",
            customer_id, e
        )
        raise


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY: Evaluate Rules
# ─────────────────────────────────────────────────────────────────────────────

@app.activity_trigger(input_name="payload")
def activity_evaluate_rules(payload: dict) -> dict:
    """
    Combines text rule hits (from LLM) with AGL structured signals to produce
    a final churn score in [0, 1].

    AGL structured signals scored (in shared/rules.py → score_event()):
        - property_listing_status: FOR_SALE or FOR_RENT  (+0.35 — highest weight)
        - contract_end_date within 60 days               (+0.20)
        - last_bill_amount >25% above prev_bill_amount   (+0.20)
        - conditional_discount_removed                   (+0.15)

    should_emit = True  iff  score >= LEAD_SCORE_THRESHOLD (default 0.60)

    Input:  { text_result, features, event: {note_id, ts} }
    Output: evaluation result dict (passed to activity_write_lead_card if should_emit)
    """
    logger.info("activity_evaluate_rules started.")
    try:
        t0 = time.time()
        text_result = payload["text_result"]
        features = payload["features"]
        event = payload["event"]
        customer_id = features.get("customer_id")

        logger.info("Evaluating churn rules for customer_id: %s", customer_id)

        ruleset, ruleset_version = load_active_ruleset()
        score, details = score_event(ruleset, text_result, features)

        # Serialise any remaining date fields in the snapshot
        serializable_features = features.copy()
        for key, value in serializable_features.items():
            if isinstance(value, (datetime, date)):
                serializable_features[key] = value.isoformat()

        should_emit = score >= THRESHOLD
        logger.info(
            "Churn evaluation completed for customer_id: %s. Score: %.3f, Threshold: %.3f, Emit: %s",
            customer_id, score, THRESHOLD, should_emit
        )
        logger.info("Metric: churn_score=%.3f", score)
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


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY: Write Lead Card
# ─────────────────────────────────────────────────────────────────────────────

@app.activity_trigger(input_name="payload")
def activity_write_lead_card(payload: dict) -> dict:
    """
    Persists a retention lead card to dbo.lead_cards.
    Only called when the churn score exceeds LEAD_SCORE_THRESHOLD.

    The explanation_text is PII-scrubbed before storage.

    Input:  evaluation result dict from activity_evaluate_rules
    Output: { "ok": True }
    """
    logger.info("activity_write_lead_card started.")
    customer_id = payload.get("customer_id")
    try:
        logger.info("Writing retention lead card for customer_id: %s", customer_id)
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
            scrub_text(payload["explanation_text"]),  # PII-safe before storage
            payload["agent_version"],
            payload["ruleset_version"]
        ]
        sql_client.fetch_one(sql, params)
        logger.info("Successfully wrote retention lead card for customer_id: %s", customer_id)
        return {"ok": True}

    except KeyError as ke:
        logger.error("Missing key in payload for activity_write_lead_card: %s", ke)
        raise
    except Exception as e:
        logger.error(
            "An error occurred in activity_write_lead_card for customer_id %s: %s",
            customer_id, e
        )
        raise