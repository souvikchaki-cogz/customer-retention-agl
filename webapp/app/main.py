import logging
from typing import Any, Dict
import httpx
import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Import all config/environment variables from one place
from shared.config import (
    LOG_LEVEL, FUNCTION_START_URL, FUNCTION_BASE_URL, FUNCTION_CODE
)

# Import API schemas from shared.models instead of defining locally
from shared.models import (
    EvaluateRequest, EvaluateResponse,
    PredictResponse, TriggerStat,
    ExistingTrigger, ExistingTriggersResponse,
    ApproveTriggerRequest, ApproveTriggerResponse,
    DeleteTriggerResponse
)

from shared.discovery import generate_triggers, PROMPT
from .db import fetch_existing_triggers, delete_trigger, update_rules_library_with_new_trigger

# Load environment variables from a .env file if present. This is idempotent and safe.
load_dotenv()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)
logger.debug("Logging configured with level %s", LOG_LEVEL)

app = FastAPI(title="Customer Retention System API")

INSTANCE_STATUS_URLS: dict[str, str] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static"))
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")

@app.get('/api/health')
async def health():
    return {"status": "ok"}

async def _call_function_start(customer_id: str, note: str) -> Dict[str, Any]:
    if FUNCTION_START_URL:
        url = FUNCTION_START_URL
    else:
        if not FUNCTION_CODE:
            raise RuntimeError("FUNCTION_CODE env var required when FUNCTION_START_URL not provided")
        url = f"{FUNCTION_BASE_URL}/api/http_start_single_analysis?code={FUNCTION_CODE}"
    payload = {"customer_id": customer_id, "note": note}
    logger.debug("Calling Azure Function start URL=%s payload(customer_id,note)=%s", url, payload)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload)
        if r.status_code >= 400:
            logger.error("Function start failed %s %s", r.status_code, r.text)
            raise HTTPException(status_code=502, detail=f"Function start failed: {r.status_code}")
        return r.json()

async def _call_status(url: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        if r.status_code >= 400:
            logger.warning("Status poll failed %s %s", r.status_code, r.text)
            raise HTTPException(status_code=502, detail=f"Status poll failed: {r.status_code}")
        return r.json()

@app.post('/api/evaluate', response_model=EvaluateResponse)
async def evaluate(req: EvaluateRequest):
    logger.debug("Evaluate called for customer_id=%s", req.customer_id)
    try:
        start_resp = await _call_function_start(req.customer_id, req.note)
    except Exception as e:
        logger.exception("Failed starting orchestration")
        raise HTTPException(status_code=500, detail=f"Failed to start evaluation: {e}")

    instance_id = start_resp.get("id")
    status_query_url = start_resp.get("statusQueryGetUri")
    runtime_status = None
    progress = None
    custom_status = None
    if status_query_url:
        try:
            status_data = await _call_status(status_query_url)
            runtime_status = status_data.get("runtimeStatus")
            custom_status = status_data.get("customStatus") or {}
            progress = custom_status.get("progress")
        except Exception:
            logger.debug("Initial status poll failed; returning start metadata only")

    if instance_id and status_query_url:
        INSTANCE_STATUS_URLS[instance_id] = status_query_url

    internal_status_url = f"/api/evaluate/status/{instance_id}" if instance_id else None

    return EvaluateResponse(
        customer_id=req.customer_id,
        instance_id=instance_id,
        status_query_url=internal_status_url,
        runtime_status=runtime_status,
        progress=progress,
        status=(custom_status or {}).get("status") if custom_status else None,
    )

class StatusResponse(BaseModel):
    instance_id: str
    runtime_status: str | None = None
    status: str | None = None
    progress: int | None = None
    result: dict | None = None

@app.get('/api/evaluate/status/{instance_id}', response_model=StatusResponse)
async def evaluate_status(instance_id: str):
    url = INSTANCE_STATUS_URLS.get(instance_id)
    if not url:
        raise HTTPException(status_code=404, detail="Unknown instance id")
    try:
        data = await _call_status(url)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Status fetch failed: {e}")
    custom_status = data.get("customStatus") or {}
    return StatusResponse(
        instance_id=instance_id,
        runtime_status=data.get("runtimeStatus"),
        status=custom_status.get("status"),
        progress=custom_status.get("progress"),
        result=custom_status.get("result"),
    )

@app.post('/api/predict', response_model=PredictResponse)
async def predict():
    try:
        logger.debug("Predict endpoint invoked")
        structured_raw = generate_triggers(prompt=PROMPT)
        structured_models = [TriggerStat(**item) for item in structured_raw]
        return PredictResponse(triggers=structured_models)
    except Exception as e:
        logger.exception("Prediction failed")
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")

@app.get('/api/triggers', response_model=ExistingTriggersResponse)
async def get_existing_triggers(limit: int = 25):
    try:
        logger.debug("Fetching existing triggers limit=%d", limit)
        rows = fetch_existing_triggers(limit=limit)
        return ExistingTriggersResponse(triggers=[ExistingTrigger(**r) for r in rows])
    except Exception as e:  # pragma: no cover
        logger.exception("Failed to fetch existing triggers")
        raise HTTPException(status_code=500, detail=f"Failed to fetch triggers: {e}")

def _derive_severity(support: float, lift: float, odds_ratio: float, p_value: float, fdr: float) -> str:
    if p_value < 0.01 and fdr < 0.02 and (lift >= 2 or odds_ratio >= 3):
        return 'HIGH'
    if p_value < 0.05 and (lift >= 1.6 or odds_ratio >= 2):
        return 'MEDIUM'
    return 'LOW'

def _build_explanation(req: ApproveTriggerRequest, severity: str) -> str:
    return (
        f"Trigger '{req.phrase}' classified {severity} severity: support={req.support:.1%}, "
        f"lift={req.lift:.2f}, odds_ratio={req.odds_ratio:.2f}, p={req.p_value:.3f}, fdr={req.fdr:.3f}."
    )

@app.post('/api/triggers/approve', response_model=ApproveTriggerResponse)
async def approve_trigger(req: ApproveTriggerRequest):
    try:
        severity = _derive_severity(req.support, req.lift, req.odds_ratio, req.p_value, req.fdr)
        explanation = _build_explanation(req, severity)
        inserted = update_rules_library_with_new_trigger(
            phrase=req.phrase,
            example_phrases=req.example_phrases,
            odds_ratio=req.odds_ratio
        )
        return ApproveTriggerResponse(
            phrase=req.phrase,
            severity=severity,
            inserted=inserted,
            explanation=explanation,
        )
    except Exception as e:
        logger.exception("Failed to approve trigger")
        raise HTTPException(status_code=500, detail=f"Failed to approve trigger: {e}")

@app.delete('/api/triggers/{trigger_id}', response_model=DeleteTriggerResponse)
async def delete_trigger_endpoint(trigger_id: int):
    try:
        deleted = delete_trigger(trigger_id)
        return DeleteTriggerResponse(id=trigger_id, deleted=deleted)
    except Exception as e:
        logger.exception("Failed to delete trigger id=%s", trigger_id)
        raise HTTPException(status_code=500, detail=f"Failed to delete trigger: {e}")

@app.get('/')
async def root(request: Request):
    index_path = os.path.join(STATIC_DIR, 'index.html')
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type='text/html')
    return {"message": "Static frontend not found"}

@app.get('/finops')
async def finops_page(request: Request):
    finops_path = os.path.join(STATIC_DIR, 'finops.html')
    if os.path.isfile(finops_path):
        return FileResponse(finops_path, media_type='text/html')
    return {"message": "FinOps page not found"}