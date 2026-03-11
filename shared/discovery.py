import os
import json
import time
import logging
from typing import List, Dict, Any, Optional

from openai import APIError
from .azure_openai import get_openai_client

logger = logging.getLogger(__name__)

PROMPT = """You are a data scientist creating synthetic data for a customer churn model 
at AGL, an Australian electricity and gas retailer.

Your task is to identify 5 high-level **themes** of customer behaviour that indicate 
a risk of switching to another energy retailer or closing their account.

The themes should be directly related to the following known churn drivers:
- Move-out or life events (selling/renting property, moving interstate).
- Bill shock or sudden cost increase.
- Active price comparison behaviour (Energy Made Easy, competitor enquiries).
- Conditional discount or concession removal.
- Contract expiry or end-of-fixed-term switching window.

For each of the 5 themes, you must provide:
1.  A full-sentence description of the specific customer behaviour under the key "description".
    The sentence must follow this exact style — it should start with a gerund verb (e.g. "Requesting", "Asking", "Expressing", "Mentioning", "Stating")
    and describe what the customer is saying or doing, as if written by a contact centre analyst.
    The description MUST be STRICTLY UNDER 55 CHARACTERS including the trailing full stop.
    Examples of the correct style (all under 55 characters):
      - "Stating a move out from the property."          (37 chars)
      - "Expressing concern over a high bill."           (36 chars)
      - "Asking about switching process or timeframe."   (44 chars)
      - "Mentioning financial hardship or payment issue." (48 chars)
      - "Requesting a refund before account closure."     (44 chars)
    Do NOT use abstract noun-phrase labels like "Life Event Disruption" or "Bill Sensitivity".
    Do NOT write descriptions longer than 55 characters.
2.  A single string of representative, comma-separated phrases for that theme under the key "example_phrases".
3.  Synthetic but realistic statistics (support, lift, odds_ratio, p_value, fdr).
4.  A unique, business-friendly **narrative explanation** under the key "narrative_explanation".
5.  A metrics_explanation object containing simple, business-friendly explanations for support, lift, and odds_ratio.

The output must be a JSON object with a single key "triggers", which contains an array of 5 objects.

Example output format:
{
  "triggers": [
    {
      "description": "Stating a move out from the property.",
      "example_phrases": "final meter read, moving house, selling the property, close my account",
      "support": 120,
      "lift": 4.2,
      "odds_ratio": 6.1,
      "p_value": 0.0001,
      "fdr": 0.0003,
      "narrative_explanation": "Customers requesting final meter reads or mentioning property sales are near-certain churners within days to weeks. Proactive outreach offering a seamless address transfer is the only effective retention lever.",
      "metrics_explanation": {
        "support": "Represents the number of at-risk customers exhibiting this behaviour.",
        "lift": "These customers are 4.2x more likely to churn compared to the average customer.",
        "odds_ratio": "The odds of account closure are 6.1x higher when this signal is present."
      }
    }
  ]
}

Do not include any text outside the JSON object."""


def _truncate_description(text: str, max_chars: int = 55) -> str:
    """Truncate description to max_chars at a word boundary, preserving trailing full stop."""
    if len(text) <= max_chars:
        return text
    # Strip trailing punctuation before truncating
    stripped = text.rstrip(".")
    # Truncate at last word boundary within limit (leave room for full stop)
    truncated = stripped[: max_chars - 1].rsplit(" ", 1)[0]
    return truncated.rstrip(",") + "."


def _fallback_structured() -> List[Dict[str, Any]]:
    """Provides a fallback list of triggers matching the new data contract."""
    base = [
    {
        "description": "Requesting a refund before account closure.",
        "example_phrases": "final meter read, selling the property, moving house, close my account",
        "narrative_explanation": "Customers requesting final meter reads or mentioning a property sale are near-certain churners. Without a seamless account transfer offer, these customers are lost by default.",
        "support": {"value": 0.18, "explanation": "18% of churned customers showed this behaviour in their final interaction."},
        "lift": {"value": 4.2, "explanation": "These customers are 4.2x more likely to churn than the average customer."},
        "odds_ratio": {"value": 6.1, "explanation": "The odds of account closure are 6.1x higher when this signal is present."},
        "p_value": 0.0001,
        "fdr": 0.0002,
    },
    {
        "description": "Expressing concern over a high bill.",
        "example_phrases": "shopping around, comparing retailers, this bill is too high, Energy Made Easy",
        "narrative_explanation": "A sudden bill increase triggers active comparison behaviour. In Australia, switching energy retailers is low-friction — once comparison starts, retention probability drops sharply without a proactive offer.",
        "support": {"value": 0.22, "explanation": "22% of at-risk customers exhibit bill-shock-driven comparison behaviour."},
        "lift": {"value": 3.1, "explanation": "These customers are 3.1x more likely to churn than the average customer."},
        "odds_ratio": {"value": 4.5, "explanation": "The odds of churn are 4.5x higher when bill shock signals are present."},
        "p_value": 0.0005,
        "fdr": 0.001,
    },
]
    return base


def generate_triggers(prompt: str = PROMPT, exclude_phrases: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Call Azure OpenAI, expecting a JSON object with a 'triggers' key."""
    final_prompt = prompt
    if exclude_phrases:
        final_prompt += (
            "\n\nThe following triggers already exist in the system. "
            "Do NOT generate any trigger that is semantically similar to these — "
            "even if the wording is different. Each new trigger must describe a "
            "clearly distinct customer behaviour or situation not already covered below:\n"
            + json.dumps(exclude_phrases, indent=2)
        )
    try:
        client = get_openai_client()
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENTNAME")
    except (ValueError, Exception) as e:
        logger.info("Azure OpenAI client could not be initialized (%s); returning fallback structured triggers", e)
        return _fallback_structured()

    payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful data scientist assistant for AGL, an Australian energy retailer."},
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
        if not isinstance(trigger_list, list):
            return _fallback_structured()

        REQUIRED_TRIGGER_KEYS = {
            "description",
            "example_phrases",
            "narrative_explanation",
            "metrics_explanation",
            "support",
            "lift",
            "odds_ratio",
        }

        for item in trigger_list[:5]:
            if not isinstance(item, dict):
                continue
            if not REQUIRED_TRIGGER_KEYS.issubset(item.keys()):
                logger.warning(
                    "Skipping trigger item — missing required keys. Present keys: %s",
                    list(item.keys())
                )
                continue
            try:
                metrics_exp = item.get("metrics_explanation", {})
                support_count = int(item["support"])
                support_float = min(support_count / 1000.0, 1.0)

                # Hard guard: truncate description to 55 chars at word boundary
                description = _truncate_description(str(item["description"]), max_chars=55)
                if len(description) != len(str(item["description"])):
                    logger.warning(
                        "Description truncated from %d to %d chars: %r",
                        len(str(item["description"])), len(description), description
                    )

                parsed.append({
                    "description": description,
                    "example_phrases": str(item["example_phrases"]),
                    "narrative_explanation": str(item["narrative_explanation"]),
                    "support": {
                        "value": support_float,
                        "explanation": metrics_exp.get("support", "The proportion of at-risk customers exhibiting this theme."),
                    },
                    "lift": {
                        "value": float(item["lift"]),
                        "explanation": metrics_exp.get("lift", "How much more likely these customers are to churn compared to average."),
                    },
                    "odds_ratio": {
                        "value": float(item["odds_ratio"]),
                        "explanation": metrics_exp.get("odds_ratio", "The odds of churn when this theme is present versus when it is not."),
                    },
                    "p_value": float(item.get("p_value", 0.0)),
                    "fdr": float(item.get("fdr", 0.0)),
                })
            except (ValueError, TypeError, KeyError) as e:
                logger.warning("Skipping trigger item due to parsing error: %s", e)
                continue

        if not parsed:
            logger.warning("Parsed 0 triggers from OpenAI response. Returning fallback.")
            return _fallback_structured()
        return parsed

    except Exception:
        return _fallback_structured()