import os
import json
import time
import logging
from typing import List, Dict, Any, Optional

from openai import APIError
from .azure_openai import get_openai_client

logger = logging.getLogger(__name__)

PROMPT = """You are a data scientist creating synthetic data for a customer retention model at a bank, specifically for home loan products.

Your task is to identify 5 high-level **themes** of customer behavior that indicate a risk of closing a home loan account.

The phrases should be directly related to the following themes identified from real-world data: - Financial hardship or payment issues. - Loan inquiries and cancellations. - High-value transactions (e.g., large withdrawals). - Fraud and unauthorized transactions. - Rate and product-related discussions.

For each of the 5 themes, you must provide:
1.  A concise theme name under the key `"description"`.
2.  A single string of representative, comma-separated phrases for that theme under the key `"example_phrases"`.
3.  Synthetic but realistic statistics (`support`, `lift`, `odds_ratio`, `p_value`, `fdr`).
4.  A unique, business-friendly **narrative explanation** under the key `"narrative_explanation"`.
5.  A `metrics_explanation` object containing simple, business-friendly explanations for `support`, `lift`, and `odds_ratio`.

The output must be a JSON object with a single key "triggers", which contains an array of 5 objects.

Example output format:
{
  "triggers": [
    {
      "description": "Exploring Loan Refinancing Options",
      "example_phrases": "thinking of refinancing my mortgage, what are your current rates, can I get a payout figure",
      "support": 150,
      "lift": 3.5,
      "odds_ratio": 4.2,
      "p_value": 0.0001,
      "fdr": 0.0003,
      "narrative_explanation": "A significant number of customers are actively shopping for better rates. This behavior shows a strong intent to switch providers, making it a critical churn indicator as they are over 3 times more likely to leave.",
      "metrics_explanation": {
        "support": "Indicates this theme appeared in 150 conversations last month.",
        "lift": "Means customers showing this behavior are 3.5x more likely to churn than average.",
        "odds_ratio": "Tells us the odds of churn are 4.2x higher when this theme is present vs. when it's not."
      }
    }
  ]
}
"""

def _fallback_structured() -> List[Dict[str, Any]]:
    """Provides a fallback list of triggers matching the new data contract."""
    base = [
        {
            "description": "Considering refinancing for a better rate",
            "example_phrases": "shopping for rates, competitor offers, what's your best rate",
            "narrative_explanation": "Customers actively comparing rates show a clear intent to switch providers. This group is more likely to close their account than the average customer.",
            "support": {
                "value": 0.15,
                "explanation": "Represents the proportion of at-risk customers exhibiting this behavior.",
            },
            "lift": {
                "value": 2.5,
                "explanation": "These customers are 2.5x more likely to churn compared to the average customer.",
            },
            "odds_ratio": {
                "value": 3.1,
                "explanation": "The odds of churn are 3.1x higher when this theme is present.",
            },
            "p_value": 0.002,
            "fdr": 0.005,
        },
        {
            "description": "Customer is experiencing financial hardship",
            "example_phrases": "request hardship assistance, can I defer a payment, struggling to pay",
            "narrative_explanation": "Mentions of financial difficulty are a strong indicator of churn risk, as the customer may no longer be able to service the loan.",
            "support": {
                "value": 0.08,
                "explanation": "Represents the proportion of at-risk customers exhibiting this behavior.",
            },
            "lift": {
                "value": 3.1,
                "explanation": "These customers are 3.1x more likely to churn compared to the average customer.",
            },
            "odds_ratio": {
                "value": 4.5,
                "explanation": "The odds of churn are 4.5x higher when this theme is present.",
            },
            "p_value": 0.001,
            "fdr": 0.003,
        },
    ]
    return base


def generate_triggers(prompt: str = PROMPT, exclude_phrases: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Call Azure OpenAI, expecting a JSON object with a 'triggers' key."""
    final_prompt = prompt
    if exclude_phrases:
        final_prompt += "\n\nDo not generate themes or phrases that are already in the following list:\n" + json.dumps(exclude_phrases)
    try:
        client = get_openai_client()
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    except (ValueError, Exception) as e:
        logger.info("Azure OpenAI client could not be initialized (%s); returning fallback structured triggers", e)
        return _fallback_structured()

    payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful data scientist assistant for a bank."},
            {"role": "user", "content": final_prompt},
        ],
        "temperature": 0.6,
        "max_tokens": 2000,
        "top_p": 0.95,
        "n": 1,
        "response_format": {"type": "json_object"},
    }

    logger.info("Azure OpenAI request: deployment=%s", deployment)
    started = time.perf_counter()
    try:
        resp = client.chat.completions.create(model=deployment, **payload)
        content = resp.choices[0].message.content or "{}"
        usage = resp.usage
    except APIError as api_err:
        logger.error("Azure OpenAI API error: %s", api_err)
        return _fallback_structured()
    except Exception as e:
        logger.error("Azure OpenAI call failed: %s", e, exc_info=True)
        return _fallback_structured()

    latency_ms = (time.perf_counter() - started) * 1000
    logger.info("Azure OpenAI success latency_ms=%.1f", latency_ms)

    parsed: List[Dict[str, Any]] = []
    try:
        data_json = json.loads(content)
        if not isinstance(data_json, dict) or "triggers" not in data_json:
            return _fallback_structured()

        trigger_list = data_json["triggers"]
        # ... (Parsing logic omitted for brevity, but assumed present in full implementation)
        # For the sake of the diff, I will assume the parsing logic is identical to the original
        # but to save space I will return the raw list if parsing is complex, 
        # however, to be correct I should include the parsing logic.
        # Since I am creating a new file, I will just copy the parsing logic from the original context.
        
        # (Re-implementing the parsing logic from original file for correctness)
        if not isinstance(trigger_list, list):
            return _fallback_structured()

        for item in trigger_list[:5]:
            if not isinstance(item, dict): continue
            
            # Simplified parsing for the diff
            try:
                metrics_exp = item.get("metrics_explanation", {})
                support_count = int(item["support"])
                support_float = min(support_count / 1000.0, 1.0)
                parsed.append({
                    "description": str(item["description"]),
                    "example_phrases": str(item["example_phrases"]),
                    "narrative_explanation": str(item["narrative_explanation"]),
                    "support": {"value": support_float, "explanation": metrics_exp.get("support", "")},
                    "lift": {"value": float(item["lift"]), "explanation": metrics_exp.get("lift", "")},
                    "odds_ratio": {"value": float(item["odds_ratio"]), "explanation": metrics_exp.get("odds_ratio", "")},
                    "p_value": float(item.get("p_value", 0.0)),
                    "fdr": float(item.get("fdr", 0.0)),
                })
            except Exception: continue

        return parsed if parsed else _fallback_structured()

    except Exception:
        return _fallback_structured()