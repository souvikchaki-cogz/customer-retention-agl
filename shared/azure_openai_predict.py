"""Azure OpenAI integration for generative churn-trigger prediction (Workflow: Predict).

Used by the webapp's /api/predict endpoint.
Falls back to a deterministic sample list if AOAI is not configured.
"""
import os
import json
import time
import logging
import requests
from typing import List, Dict, Any

PROMPT = (
    "Generate exactly 5 potential churn triggers (short phrases) for a retail banking "
    "customer along with synthetic statistical metrics. "
    "Return ONLY valid JSON array of 5 objects, no commentary. Each object MUST have keys: "
    "phrase (string), support (float 0-1), lift (float), odds_ratio (float), "
    "p_value (float <= 0.1), fdr (float <= 0.1). "
    'Example: [{"phrase":"High fees","support":0.18,"lift":1.9,"odds_ratio":2.1,'
    '"p_value":0.012,"fdr":0.018}, ...]'
)

logger = logging.getLogger(__name__)


class AzureOpenAIConfigError(RuntimeError):
    pass


def _get_config():
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if not all([endpoint, api_key, deployment]):
        raise AzureOpenAIConfigError("Azure OpenAI env vars not fully set")
    assert endpoint is not None
    return endpoint.rstrip("/"), api_key, deployment


def _fallback_structured() -> List[Dict[str, Any]]:
    base = [
        {"phrase": "High or unexpected fees", "support": 0.22, "lift": 1.8, "odds_ratio": 2.3, "p_value": 0.014, "fdr": 0.019},
        {"phrase": "Poor mobile app UX", "support": 0.19, "lift": 1.6, "odds_ratio": 2.0, "p_value": 0.021, "fdr": 0.027},
        {"phrase": "Unresolved service complaints", "support": 0.16, "lift": 2.1, "odds_ratio": 3.2, "p_value": 0.008, "fdr": 0.013},
        {"phrase": "Better competitor incentives", "support": 0.24, "lift": 1.5, "odds_ratio": 1.9, "p_value": 0.037, "fdr": 0.045},
        {"phrase": "Security / trust concerns", "support": 0.11, "lift": 2.4, "odds_ratio": 3.6, "p_value": 0.005, "fdr": 0.010},
    ]
    for b in base:
        b["explanation"] = (
            f"'{b['phrase']}' occurs in ~{b['support']*100:.1f}% of at-risk customers "
            f"(lift {b['lift']:.2f}, OR {b['odds_ratio']:.2f}); "
            f"p={b['p_value']:.3f}, fdr={b['fdr']:.3f}."
        )
    return base


def get_triggers_via_azure_openai(prompt: str = PROMPT) -> List[Dict[str, Any]]:
    """Call Azure OpenAI for trigger prediction. Falls back on config/parse failure."""
    try:
        endpoint, api_key, deployment = _get_config()
    except AzureOpenAIConfigError:
        logger.info("AOAI config missing; returning fallback triggers")
        return _fallback_structured()

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-02-15-preview"
    headers = {"api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "messages": [
            {"role": "system", "content": "You are a concise banking customer retention analyst."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.5,
        "max_tokens": 500,
        "top_p": 0.95,
        "n": 1,
    }

    started = time.perf_counter()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as e:
        logger.error("AOAI network error: %s", e)
        raise

    latency_ms = (time.perf_counter() - started) * 1000
    if not resp.ok:
        logger.error("AOAI HTTP %s latency=%.1fms", resp.status_code, latency_ms)
        resp.raise_for_status()

    data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

    parsed: List[Dict[str, Any]] = []
    try:
        js = content[content.find("["):content.rfind("]") + 1]
        for item in json.loads(js)[:5]:
            required = {"phrase", "support", "lift", "odds_ratio", "p_value", "fdr"}
            if not isinstance(item, dict) or not required.issubset(item):
                continue
            for k in ("support", "lift", "odds_ratio", "p_value", "fdr"):
                item[k] = float(item[k])
            item["explanation"] = (
                f"'{item['phrase']}' in {item['support']*100:.1f}% at-risk "
                f"(lift {item['lift']:.2f}, OR {item['odds_ratio']:.2f}); "
                f"p={item['p_value']:.3f}, fdr={item['fdr']:.3f}."
            )
            parsed.append(item)
        if len(parsed) == 5:
            return parsed
    except Exception:
        pass
    logger.warning("AOAI parse issue; falling back")
    return _fallback_structured()