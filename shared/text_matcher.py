"""Azure OpenAI text matcher using Azure OpenAI Service."""
import os
import json
import logging
import time
from typing import Dict, Any, List

from .azure_openai import get_openai_client


CONFIDENCE_FLOOR = float(os.getenv("CONFIDENCE_FLOOR", "0.60"))
EVIDENCE_MIN_LEN = int(os.getenv("EVIDENCE_MIN_LEN", "4"))

def _build_catalog(ruleset: Dict[str, Any]) -> List[Dict[str, Any]]:
    cat=[]
    for key, r in (ruleset.get("text_rules") or {}).items():
        cat.append({
            "id": r.get("id", key),
            "name": key,
            "description": r.get("description", ""),
            "phrase_hints": r.get("phrase_hints", []),
            "negations": r.get("negations", [])
        })
    return cat

def match_text_rules(text: str, ruleset: Dict[str, Any]) -> Dict[str, Any]:
    start = time.time()
    logging.info("match_text_rules started.")

    try:
        client = get_openai_client()
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    except (ValueError, Exception) as e:
        logging.error("AzureOpenAI client could not be initialized (%s). Cannot match text rules.", e)
        return {"rule_hits": [], "error": "OpenAI client could not be initialized."}

    catalog = _build_catalog(ruleset)

    system = (
        "You are a precise text-trigger detector for a bank.\n"
        "Use ONLY these rule IDs and meanings:\n"
        f"{json.dumps(catalog, ensure_ascii=False)}\n\n"
        'Return JSON exactly: {"rule_hits":[{"rule_id":"<ID>","confidence":0.0,"description":"<description field value>","evidence_text":"<substring or substrings if multiple evidences>","explanation":"<explanation of why this has given confidence>"}]}\n'
        "- confidence in [0,1].\n"
        "- evidence_text must be a short substring copied from the note.\n"
        "- Consider all the rules despite confidence (no filtering), but provide a rule only once.\n"
    )
    user = f"NOTE:\n{text}\nReturn JSON only."

    usage = {}
    try:
        logging.info("Calling Azure OpenAI for text matching. Model: %s", deployment)
        resp = client.chat.completions.create(
            model=deployment,
            messages=[{"role":"system","content":system},
                      {"role":"user","content":user}],
            temperature=0,
            response_format={"type":"json_object"},
        )
        content = resp.choices[0].message.content

        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens
            }
            logging.info("Successfully received and parsed response from Azure OpenAI. Tokens: %s", usage)
        else:
            logging.info("Successfully received and parsed response from Azure OpenAI. Usage data not available.")

        raw = json.loads(content)

    except Exception as e:
        logging.error("Error calling Azure OpenAI or parsing response: %s", e, exc_info=True)
        raw = {"rule_hits": []}

    # local clean-up / floors
    cleaned = []
    for h in raw.get("rule_hits", []):
        rid = h.get("rule_id")
        conf = float(h.get("confidence", 0) or 0)
        ev = (h.get("evidence_text") or "").strip()
        desc = (h.get("description") or "").strip()
        expl = (h.get("explanation") or "").strip()

        hit = len(ev) >= EVIDENCE_MIN_LEN and conf >= CONFIDENCE_FLOOR

        cleaned.append({
            "rule_id": rid,
            "confidence": conf,
            "hit": hit,
            "evidence_text": ev,
            "description": desc,
            "explanation": expl
        })

    for rule in catalog:
        rule_id = rule.get("id")
        if not any(cleaned_rule["rule_id"] == rule_id for cleaned_rule in cleaned):
            cleaned.append({"rule_id": rule_id, "confidence": 0.0, "hit": False, "evidence_text": "", "description": rule.get("description", ""), "explanation": ""})

    latency = int((time.time() - start) * 1000)
    logging.info("match_text_rules completed in %d ms. Found %d final hits.", latency, len(raw))

    return {"rule_hits": cleaned, "llm_used": deployment, "model_latency_ms": latency, "token_usage": usage}