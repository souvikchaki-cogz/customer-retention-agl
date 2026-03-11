from pydantic import BaseModel
from typing import Optional, List

class EvaluateRequest(BaseModel):
    customer_id: str
    note: str

class EvaluateResponse(BaseModel):
    message: str = "Evaluation Triggered"
    customer_id: str
    instance_id: Optional[str] = None
    status_query_url: Optional[str] = None
    runtime_status: Optional[str] = None
    progress: Optional[int] = None
    status: Optional[str] = None

class Metric(BaseModel):
    value: float
    explanation: str

class TriggerStat(BaseModel):
    # discovery_id is populated when the trigger originates from agl_discovery_cards
    # (i.e. was fetched from DB by /api/predict rather than generated live).
    # It is None for fallback/offline triggers that were never written to DB.
    discovery_id: Optional[int] = None
    description: str
    example_phrases: str
    narrative_explanation: str
    support: Metric
    lift: Metric
    odds_ratio: Metric
    p_value: float
    fdr: float

class PredictResponse(BaseModel):
    triggers: List[TriggerStat]

# DiscoveryCard mirrors a single row from agl_discovery_cards as returned
# by fetch_candidate_discovery_cards(). Used internally by /api/predict.
class DiscoveryCard(BaseModel):
    discovery_id: int
    phrase: str
    support: float
    lift: float
    odds_ratio: float
    fdr: float
    p_value: float
    examples_json: Optional[str] = None
    status: str = "CANDIDATE"

class ExistingTrigger(BaseModel):
    id: Optional[int] = None
    phrase: str
    severity: Optional[str] = None
    support: Optional[float] = None
    lift: Optional[float] = None
    odds_ratio: Optional[float] = None
    p_value: Optional[float] = None
    fdr: Optional[float] = None
    explanation: Optional[str] = None

class ExistingTriggersResponse(BaseModel):
    triggers: List[ExistingTrigger]

class ApproveTriggerRequest(BaseModel):
    # discovery_id links back to agl_discovery_cards so the approve endpoint
    # can stamp the row as APPROVED alongside writing to agl_rules_library.
    discovery_id: int
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

class RejectTriggerRequest(BaseModel):
    discovery_id: int

class RejectTriggerResponse(BaseModel):
    discovery_id: int
    rejected: bool

class DeleteTriggerResponse(BaseModel):
    id: int
    deleted: bool

class StatusResponse(BaseModel):
    instance_id: str
    runtime_status: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[int] = None
    result: Optional[dict] = None