from pydantic import BaseModel
from typing import Optional, List

class EvaluateRequest(BaseModel):
    customer_id: str
    note: str

class EvaluateResponse(BaseModel):
    message: str = "Evaluation Triggered"
    customer_id: Optional[str] = None
    instance_id: Optional[str] = None
    status_query_url: Optional[str] = None
    runtime_status: Optional[str] = None
    progress: Optional[int] = None
    status: Optional[str] = None

class TriggerStat(BaseModel):
    description: str
    example_phrases: str
    narrative_explanation: str
    support: float
    lift: float
    odds_ratio: float
    p_value: float
    fdr: float

class PredictResponse(BaseModel):
    triggers: List[TriggerStat]

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