"""
Unit tests for shared/discovery.py

Run from project root:
    pytest tests/test_discovery.py -v
"""
import json
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from shared.discovery import generate_triggers, _fallback_structured, PROMPT


class TestFallbackStructured:
    """Tests for the static fallback data."""

    def test_returns_list(self):
        result = _fallback_structured()
        assert isinstance(result, list)

    def test_returns_at_least_one_trigger(self):
        result = _fallback_structured()
        assert len(result) >= 1

    def test_trigger_has_required_keys(self):
        result = _fallback_structured()
        required_keys = {"description", "example_phrases", "narrative_explanation",
                         "support", "lift", "odds_ratio", "p_value", "fdr"}
        for trigger in result:
            assert required_keys.issubset(trigger.keys()), (
                f"Trigger missing keys: {required_keys - trigger.keys()}"
            )

    def test_support_is_metric_dict(self):
        result = _fallback_structured()
        for trigger in result:
            assert isinstance(trigger["support"], dict)
            assert "value" in trigger["support"]
            assert "explanation" in trigger["support"]

    def test_lift_is_metric_dict(self):
        result = _fallback_structured()
        for trigger in result:
            assert isinstance(trigger["lift"], dict)
            assert "value" in trigger["lift"]

    def test_odds_ratio_is_metric_dict(self):
        result = _fallback_structured()
        for trigger in result:
            assert isinstance(trigger["odds_ratio"], dict)
            assert "value" in trigger["odds_ratio"]

    def test_numeric_fields_are_floats(self):
        result = _fallback_structured()
        for trigger in result:
            assert isinstance(trigger["p_value"], float)
            assert isinstance(trigger["fdr"], float)
            assert isinstance(trigger["support"]["value"], float)
            assert isinstance(trigger["lift"]["value"], float)
            assert isinstance(trigger["odds_ratio"]["value"], float)


class TestGenerateTriggers:
    """Tests for the generate_triggers function."""

    def test_returns_fallback_when_openai_unavailable(self):
        """When OpenAI client cannot be initialised, fallback data should be returned."""
        with patch("shared.discovery.get_openai_client", side_effect=ValueError("No key")):
            result = generate_triggers()
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_returns_fallback_on_api_error(self):
        """When the OpenAI API call fails, fallback data should be returned."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API down")
        with patch("shared.discovery.get_openai_client", return_value=mock_client):
            result = generate_triggers()
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_returns_fallback_on_bad_json(self):
        """When the API returns malformed JSON, fallback data should be returned."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "not valid json {"
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.discovery.get_openai_client", return_value=mock_client):
            result = generate_triggers()
        assert isinstance(result, list)

    def test_returns_fallback_when_triggers_key_missing(self):
        """When JSON response lacks 'triggers' key, fallback should be returned."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps({"something_else": []})
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.discovery.get_openai_client", return_value=mock_client):
            result = generate_triggers()
        assert isinstance(result, list)

    def test_parses_valid_openai_response(self):
        """When the API returns a valid response, parsed triggers should be returned."""
        valid_payload = {
            "triggers": [
                {
                    "description": "Move-Out Intent",
                    "example_phrases": "final meter read, moving house, close my account",
                    "support": 150,
                    "lift": 3.5,
                    "odds_ratio": 4.2,
                    "p_value": 0.0001,
                    "fdr": 0.0003,
                    "narrative_explanation": "Customers requesting final meter reads are near-certain churners.",
                    "metrics_explanation": {
                        "support": "Appeared in 150 conversations.",
                        "lift": "3.5x more likely to churn.",
                        "odds_ratio": "Odds 4.2x higher."
                    }
                }
            ]
        }
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps(valid_payload)
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.discovery.get_openai_client", return_value=mock_client):
            result = generate_triggers()
        assert len(result) == 1
        assert result[0]["description"] == "Move-Out Intent"
        assert isinstance(result[0]["support"], dict)
        assert "value" in result[0]["support"]

    def test_exclude_phrases_appended_to_prompt(self):
        """exclude_phrases should be added to the prompt to avoid duplicates."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = json.dumps({"triggers": []})
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp

        captured_calls = []
        def capture_call(**kwargs):
            captured_calls.append(kwargs)
            return mock_resp

        mock_client.chat.completions.create.side_effect = capture_call

        with patch("shared.discovery.get_openai_client", return_value=mock_client):
            generate_triggers(exclude_phrases=["final meter read", "bill shock"])

        assert len(captured_calls) == 1
        messages = captured_calls[0]["messages"]
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert "final meter read" in user_content
        assert "bill shock" in user_content

    def test_prompt_constant_is_string(self):
        assert isinstance(PROMPT, str)
        assert len(PROMPT) > 100