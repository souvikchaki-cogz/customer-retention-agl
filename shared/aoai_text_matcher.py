"""Azure OpenAI text-trigger detection against a ruleset catalog (Workflow-1).

Used by: functions/activity_call_text_agent
"""
import os
import json
import logging
import time
from typing import Dict, Any, List
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

endpoint = os.getenv("AZURE_OPENAI_API_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
deployment = os.getenv("AZURE_OPENAI_DEPLOYMENTNAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT")
api_key = os.getenv("AZURE_OPENAI_API_KEY")

logger = logging.getLogger(__name__)

_client = None

def _get_client():
    global _client
    if _client:
        return _client
    
    if api_key:
        _client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version="2025-01-01-preview")
    else:
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
        _client = AzureOpenAI(azure_endpoint=endpoint, azure_ad_token_provider=token_provider, api_version="2025-01-01-preview")
    return _client

CONFIDENCE_FLOOR = float(os.getenv("CONFIDENCE_FLOOR", "0.60"))
EVIDENCE_MIN_LEN = int(os.getenv("EVIDENCE_MIN_LEN", "4"))


def _build_catalog(ruleset: Dict[str, Any]) -> List[Dict[str, Any]]:
    cat = []
    for key, r in (ruleset.get("text_rules") or {}).items():
        cat.append({
            "id": r.get("id", key),
            "name": key,
            "description": r.get("description", ""),
            "phrase_hints": r.get("phrase_hints", []),
            "negations": r.get("negations", []),
        })
    return cat


def match_text_rules(text: str, ruleset: Dict[str, Any]) -> Dict[str, Any]:
    start = time.time()
    client = _get_client()
    catalog = _build_catalog(ruleset)
    allow_ids = {c["id"] for c in catalog}

    system = (
        "You are a precise text-trigger detector for a bank.\n"
        "Use ONLY these rule IDs and meanings:\n"
        f"{json.dumps(catalog, ensure_ascii=False)}\n\n"
        'Return JSON exactly: {"rule_hits":[{"rule_id":"<ID>","confidence":0.0,"evidence_text":"<substring>"}]}\n'
        '- confidence in [0,1].\n'
        '- evidence_text must be a short substring copied from the note.\n'
        '- If nothing matches, return {"rule_hits":[]}.'
    )
    user = f"NOTE:\n{text}\nReturn JSON only."

    content = None
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        raw = json.loads(content)
    except Exception as e:
        logger.error(f"LLM matching failed: {e}")
        raw = {"rule_hits": []}

    cleaned = []
    for h in raw.get("rule_hits", []):
        rid = h.get("rule_id")
        conf = float(h.get("confidence", 0) or 0)
        ev = (h.get("evidence_text") or "").strip()
        if rid in allow_ids and conf >= CONFIDENCE_FLOOR and len(ev) >= EVIDENCE_MIN_LEN:
            cleaned.append({"rule_id": rid, "confidence": conf, "evidence_text": ev})

    return {
        "rule_hits": cleaned,
        "llm_used": deployment,
        "model_latency_ms": int((time.time() - start) * 1000),
    }