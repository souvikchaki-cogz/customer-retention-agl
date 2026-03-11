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

The following are known churn drivers at AGL, provided as domain context only:
- Move-out or life events (selling/renting property, moving interstate).
- Bill shock or sudden cost increase.
- Active price comparison behaviour (Energy Made Easy, competitor enquiries).
- Conditional discount or concession removal.
- Contract expiry or end-of-fixed-term switching window.

These drivers are provided so you understand the business domain — NOT as a list you 
must generate themes from. Do NOT anchor your 5 themes to these drivers. Instead, think 
broadly across the full customer lifecycle and identify behaviours that signal churn risk 
but are NOT already covered by the drivers above. Look for signals such as:
- Sentiment and tone shifts (e.g. frustration, distrust, dissatisfaction with service quality).
- Self-service or digital disengagement (e.g. closing online account, unsubscribing from communications).
- Reactive retention signals (e.g. asking whether AGL will price-match, negotiating to stay).
- Life stage or usage changes (e.g. going solar, downsizing, vacancy periods).
- Service quality complaints that precede switching (e.g. repeated billing errors, unresolved disputes).

For each of the 5 themes, you must provide:
1.  A full-sentence description of the specific customer behaviour under the key "description".
    The sentence must follow this exact style — it should start with a gerund verb (e.g. "Requesting", "Asking", "Expressing", "Mentioning", "Stating")
    and describe what the customer is saying or doing, as if written by a contact centre analyst.
    The description MUST be AT MOST 55 CHARACTERS including the trailing full stop.
    You MUST craft the sentence to fit naturally within 55 characters — do NOT write a longer sentence and rely on it being shortened later.
    Before finalising each description, count its characters and confirm it is 55 or fewer.
    Examples of the correct style (all within 55 characters):
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

Before finalising your list of 5 triggers, you MUST check them against each other.
Every trigger in your list must be distinct in intent from every other trigger in your
own list — not just from the existing triggers provided later. Apply the same test you
apply against existing triggers: if two of your generated triggers describe the same
broad customer behaviour, emotion, or situation — even if the wording differs — discard
the weaker or more generic one and replace it with a trigger that covers genuinely
different ground.

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
    """Truncate description to max_chars at a word boundary, preserving trailing full stop.

    This function is retained as a last-resort guard only. It should NOT be reached
    under normal operation — the prompt instructs the LLM to generate descriptions
    within the character limit. If this function is invoked and truncation actually
    occurs, the caller treats the item as non-compliant and rejects it.
    """
    if len(text) <= max_chars:
        return text
    stripped = text.rstrip(".")
    truncated = stripped[: max_chars - 1].rsplit(" ", 1)[0]
    return truncated.rstrip(",") + "."


def _fallback_structured() -> List[Dict[str, Any]]:
    """Provides a fallback list of triggers matching the new data contract.

    These triggers represent novel churn signals that are NOT covered by the five
    known drivers listed in PROMPT (move-out, bill shock, price comparison, discount
    removal, contract expiry). They are intentionally distinct so they remain valid
    under the prompt's instruction to avoid anchoring to those drivers.
    """
    return [
        {
            "description": "Expressing frustration with repeated errors.",
            "example_phrases": (
                "nobody calls me back, this is ridiculous, terrible service, "
                "I keep getting different answers, still not fixed"
            ),
            "narrative_explanation": (
                "Repeated service failures — billing errors, unanswered callbacks, "
                "unresolved disputes — erode trust faster than price. Customers who "
                "escalate frustration in contact centre interactions are significantly "
                "more likely to switch within 30 days if the issue remains open."
            ),
            "support": {"value": 0.14, "explanation": "14% of churned customers flagged repeated service errors in their last interaction."},
            "lift": {"value": 2.8, "explanation": "These customers are 2.8x more likely to churn than the average customer."},
            "odds_ratio": {"value": 3.9, "explanation": "The odds of switching are 3.9x higher when service frustration signals are present."},
            "p_value": 0.0008,
            "fdr": 0.0015,
        },
        {
            "description": "Asking about solar or battery install options.",
            "example_phrases": (
                "solar panels, feed-in tariff, battery storage, going solar, "
                "solar rebate, rooftop solar, home battery"
            ),
            "narrative_explanation": (
                "Customers exploring solar or battery installations are evaluating a "
                "fundamental change to their energy setup. If AGL cannot offer a "
                "competitive solar feed-in tariff or integrated battery plan, these "
                "customers are likely to switch to a provider that can."
            ),
            "support": {"value": 0.11, "explanation": "11% of at-risk customers enquired about solar or battery options before churning."},
            "lift": {"value": 2.4, "explanation": "These customers are 2.4x more likely to churn than the average customer."},
            "odds_ratio": {"value": 3.2, "explanation": "The odds of churn are 3.2x higher when solar enquiry signals are present."},
            "p_value": 0.002,
            "fdr": 0.004,
        },
    ]


def generate_triggers(prompt: str = PROMPT, exclude_phrases: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Call Azure OpenAI, expecting a JSON object with a 'triggers' key."""
    final_prompt = prompt
    if exclude_phrases:
        # exclude_phrases contains the human-readable 'description' sentences of all
        # currently active churn rules (e.g. "Stating a move out from the property.").
        # Each sentence is a complete description of a customer behaviour category that
        # is already being detected. The LLM must treat each one as covering not just
        # its exact wording but also any sub-case, specialisation, or re-framing of
        # the same underlying customer intent or action.
        final_prompt += (
            "\n\nThe following are the descriptions of churn trigger categories that already "
            "exist in the system. Each is a complete sentence describing a specific customer "
            "behaviour or situation that is already being detected.\n\n"
            "BEFORE generating each new trigger, you MUST work through ALL of the following "
            "descriptions one by one and apply this test:\n"
            "  - Does my new trigger describe the same customer intent, action, or situation "
            "as this existing one — even if expressed differently?\n"
            "  - Is my new trigger a more specific version, a sub-case, a specialisation, "
            "or a re-phrasing of this existing one? For example: 'moving interstate' is a "
            "sub-case of 'move out from the property'; 'dissatisfied with price increase' is "
            "a re-phrasing of 'concern over a high bill'; 'property sale closure request' is "
            "a sub-case of both 'account closure' and 'move out'.\n"
            "  - If the answer to EITHER question is yes for ANY existing description, "
            "discard the new trigger entirely and choose a behaviour not covered at all.\n\n"
            "Each of your 5 new triggers MUST describe a customer behaviour that is "
            "completely distinct in intent — not a sub-case, not a re-phrasing, not a "
            "specialisation — from ALL of the following:\n"
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

                # Bug #1 fix: parse support as float to handle both integer counts
                # (e.g. 120) and float proportions (e.g. 0.18) returned by the LLM.
                # Values >= 1.0 are treated as raw counts and normalised to [0, 1]
                # by dividing by 1000 (capped at 1.0).
                # Values already in [0, 1) are used directly as proportions.
                support_raw = float(item["support"])
                if support_raw >= 1.0:
                    support_float = min(support_raw / 1000.0, 1.0)
                else:
                    support_float = support_raw

                raw_description = str(item["description"])

                # Guard: reject items where the LLM returned a description longer than
                # 55 characters despite the prompt instruction. _truncate_description is
                # NOT used to silently fix non-compliant output — a word-chopped description
                # is semantically worse than no description. Log and skip instead.
                if len(raw_description) > 55:
                    logger.warning(
                        "Skipping trigger item — description exceeds 55 characters (%d chars): %r. "
                        "This indicates prompt non-compliance; the item is rejected rather than truncated.",
                        len(raw_description), raw_description
                    )
                    continue

                parsed.append({
                    "description": raw_description,
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