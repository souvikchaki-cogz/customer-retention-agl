import logging
import os
from typing import Any, Dict
import httpx
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from shared.discovery import generate_triggers, PROMPT
from .db import fetch_existing_triggers, delete_trigger,update_rules_library_with_new_trigger
from dotenv import load_dotenv

# Load environment variables from a .env file if present. This is idempotent and safe.
load_dotenv()

# Logging configuration (executed once on import)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)
logger.debug("Logging configured with level %s", LOG_LEVEL)

app = FastAPI(title="Customer Retention System API")

# In-memory mapping of Durable Function instance id -> statusQuery URL
INSTANCE_STATUS_URLS: dict[str, str] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static assets (new simplified static frontend)
STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "static"))
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")

class EvaluateRequest(BaseModel):
    customer_id: str
    note: str

class EvaluateResponse(BaseModel):
    message: str = "Evaluation Triggered"
    customer_id: str
    instance_id: str | None = None
    status_query_url: str | None = None
    runtime_status: str | None = None
    progress: int | None = None
    status: str | None = None  # customStatus.status

class Metric(BaseModel):
    value: float
    explanation: str

class TriggerStat(BaseModel):
    description: str
    example_phrases: str
    narrative_explanation: str
    support: Metric
    lift: Metric
    odds_ratio: Metric
    p_value: float
    fdr: float

class PredictResponse(BaseModel):
    triggers: list[TriggerStat]

class ExistingTrigger(BaseModel):
    id: int | None = None
    phrase: str
    severity: str | None = None
    support: float | None = None
    lift: float | None = None
    odds_ratio: float | None = None
    p_value: float | None = None
    fdr: float | None = None
    explanation: str | None = None

class ExistingTriggersResponse(BaseModel):
    triggers: list[ExistingTrigger]

class ApproveTriggerRequest(BaseModel):
    phrase: str
    example_phrases: str
    support: float
    lift: float
    odds_ratio: float
    p_value: float
    fdr: float

class ApproveTriggerResponse(BaseModel):
    phrase: str
    severity: str
    inserted: bool
    explanation: str

class DeleteTriggerResponse(BaseModel):
    id: int
    deleted: bool

@app.get('/api/health')
async def health():
    return {"status": "ok"}

FUNCTION_START_URL = os.getenv("FUNCTION_START_URL")  # full URL including code OR
FUNCTION_BASE_URL = os.getenv("FUNCTION_BASE_URL", "http://imb-customer-retention.azurewebsites.net")
FUNCTION_CODE = os.getenv("FUNCTION_CODE")  # if using base + code

async def _call_function_start(customer_id: str, note: str) -> Dict[str, Any]:
    if FUNCTION_START_URL:
        url = FUNCTION_START_URL
    else:
        if not FUNCTION_CODE:
            raise RuntimeError("FUNCTION_CODE env var required when FUNCTION_START_URL not provided")
        url = f"{FUNCTION_BASE_URL}/api/http_start_single_analysis?code={FUNCTION_CODE}"
    # Azure Function expects keys: customer_id and text (not 'note')
    payload = {"customer_id": customer_id, "text": note}
    logger.debug("Calling Azure Function start URL=%s payload(customer_id,text)=%s", url, payload)
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

    # Store mapping so frontend only calls internal status endpoint
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
        # Convert dicts to TriggerStat models explicitly (validation)
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
    """Naive severity derivation based on synthetic stats."""
    # Example heuristics: prioritize statistical strength & effect size
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
        # The severity and explanation are still relevant for the response,
        # but the actual insertion logic is now handled by update_rules_library_with_new_trigger
        severity = _derive_severity(req.support, req.lift, req.odds_ratio, req.p_value, req.fdr)
        explanation = _build_explanation(req, severity)
        
        inserted = update_rules_library_with_new_trigger(
            phrase=req.phrase,
            example_phrases=req.example_phrases,
            odds_ratio=req.odds_ratio
        )
        
        return ApproveTriggerResponse(
            phrase=req.phrase,
            severity=severity, # This severity is derived for the response, not used in rules_library
            inserted=inserted,
            explanation=explanation,
        )
    except Exception as e:  # pragma: no cover
        logger.exception("Failed to approve trigger")
        raise HTTPException(status_code=500, detail=f"Failed to approve trigger: {e}")


@app.delete('/api/triggers/{trigger_id}', response_model=DeleteTriggerResponse)
async def delete_trigger_endpoint(trigger_id: int):
    try:
        deleted = delete_trigger(trigger_id)
        return DeleteTriggerResponse(id=trigger_id, deleted=deleted)
    except Exception as e:  # pragma: no cover
        logger.exception("Failed to delete trigger id=%s", trigger_id)
        raise HTTPException(status_code=500, detail=f"Failed to delete trigger: {e}")

# Root route -> index.html (if static present)
@app.get('/')
async def root(request: Request):
    index_path = os.path.join(STATIC_DIR, 'index.html')
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type='text/html')
    return {"message": "Static frontend not found"}

# FinOps executive view route -> finops.html (if present)
@app.get('/finops')
async def finops_page(request: Request):
    finops_path = os.path.join(STATIC_DIR, 'finops.html')
    if os.path.isfile(finops_path):
        return FileResponse(finops_path, media_type='text/html')
    return {"message": "FinOps page not found"}