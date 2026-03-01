"""Customer Retention System — FastAPI application.

Serves the static frontend, exposes REST APIs for evaluation, prediction,
and trigger management. Calls Azure Durable Functions for orchestration.
"""
import logging
import os
from typing import Any, Dict
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from shared.azure_openai_predict import get_triggers_via_azure_openai, PROMPT
from .db import fetch_existing_triggers, insert_trigger, delete_trigger
from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Customer Retention System API")

INSTANCE_STATUS_URLS: dict[str, str] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")

# ── Pydantic Models ──────────────────────────────────────────

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
    status: str | None = None

class TriggerStat(BaseModel):
    phrase: str
    support: float = Field(ge=0, le=1)
    lift: float
    odds_ratio: float
    p_value: float
    fdr: float
    explanation: str | None = None

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

class StatusResponse(BaseModel):
    instance_id: str
    runtime_status: str | None = None
    status: str | None = None
    progress: int | None = None
    result: dict | None = None

# ── Durable Function Integration ─────────────────────────────

FUNCTION_START_URL = os.getenv("FUNCTION_START_URL")
FUNCTION_BASE_URL = os.getenv("FUNCTION_BASE_URL", "http://localhost:7071")
FUNCTION_CODE = os.getenv("FUNCTION_CODE")

async def _call_function_start(customer_id: str, note: str) -> Dict[str, Any]:
    if FUNCTION_START_URL:
        url = FUNCTION_START_URL
    else:
        if not FUNCTION_CODE:
            raise RuntimeError("FUNCTION_CODE required when FUNCTION_START_URL not set")
        url = f"{FUNCTION_BASE_URL}/api/http_start_single_analysis?code={FUNCTION_CODE}"
    payload = {"customer_id": customer_id, "text": note}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload)
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Function start failed: {r.status_code}")
        return r.json()

async def _call_status(url: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Status poll failed: {r.status_code}")
        return r.json()

# ── Routes ────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.post("/api/evaluate", response_model=EvaluateResponse)
async def evaluate(req: EvaluateRequest):
    try:
        start_resp = await _call_function_start(req.customer_id, req.note)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start evaluation: {e}")

    instance_id = start_resp.get("id")
    status_query_url = start_resp.get("statusQueryGetUri")
    runtime_status = progress = custom_status = None
    if status_query_url:
        try:
            status_data = await _call_status(status_query_url)
            runtime_status = status_data.get("runtimeStatus")
            custom_status = status_data.get("customStatus") or {}
            progress = custom_status.get("progress")
        except Exception:
            pass

    if instance_id and status_query_url:
        INSTANCE_STATUS_URLS[instance_id] = status_query_url

    return EvaluateResponse(
        customer_id=req.customer_id,
        instance_id=instance_id,
        status_query_url=f"/api/evaluate/status/{instance_id}" if instance_id else None,
        runtime_status=runtime_status,
        progress=progress,
        status=(custom_status or {}).get("status") if custom_status else None,
    )

@app.get("/api/evaluate/status/{instance_id}", response_model=StatusResponse)
async def evaluate_status(instance_id: str):
    url = INSTANCE_STATUS_URLS.get(instance_id)
    if not url:
        raise HTTPException(status_code=404, detail="Unknown instance id")
    data = await _call_status(url)
    cs = data.get("customStatus") or {}
    return StatusResponse(
        instance_id=instance_id,
        runtime_status=data.get("runtimeStatus"),
        status=cs.get("status"),
        progress=cs.get("progress"),
        result=cs.get("result"),
    )

@app.post("/api/predict", response_model=PredictResponse)
async def predict():
    try:
        raw = get_triggers_via_azure_openai(PROMPT)
        return PredictResponse(triggers=[TriggerStat(**item) for item in raw])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")

@app.get("/api/triggers", response_model=ExistingTriggersResponse)
async def get_triggers(limit: int = 25):
    rows = fetch_existing_triggers(limit=limit)
    return ExistingTriggersResponse(triggers=[ExistingTrigger(**r) for r in rows])

def _derive_severity(support, lift, odds_ratio, p_value, fdr) -> str:
    if p_value < 0.01 and fdr < 0.02 and (lift >= 2 or odds_ratio >= 3):
        return "HIGH"
    if p_value < 0.05 and (lift >= 1.6 or odds_ratio >= 2):
        return "MEDIUM"
    return "LOW"

@app.post("/api/triggers/approve", response_model=ApproveTriggerResponse)
async def approve_trigger(req: ApproveTriggerRequest):
    severity = _derive_severity(req.support, req.lift, req.odds_ratio, req.p_value, req.fdr)
    explanation = (
        f"Trigger '{req.phrase}' classified {severity}: support={req.support:.1%}, "
        f"lift={req.lift:.2f}, OR={req.odds_ratio:.2f}, p={req.p_value:.3f}, fdr={req.fdr:.3f}."
    )
    inserted = insert_trigger(req.phrase, severity)
    return ApproveTriggerResponse(phrase=req.phrase, severity=severity, inserted=inserted, explanation=explanation)

@app.delete("/api/triggers/{trigger_id}", response_model=DeleteTriggerResponse)
async def delete_trigger_endpoint(trigger_id: int):
    deleted = delete_trigger(trigger_id)
    return DeleteTriggerResponse(id=trigger_id, deleted=deleted)

@app.get("/")
async def root(request: Request):
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index):
        return FileResponse(index, media_type="text/html")
    return {"message": "Static frontend not found"}