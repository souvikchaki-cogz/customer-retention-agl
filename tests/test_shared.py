"""
Unit tests for shared/* modules (guardrails, pii, config, text_matcher, rules).

Run from project root:
    pytest tests/test_shared.py -v
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# ---------------------------------------------------------------------------
# shared/pii.py
# ---------------------------------------------------------------------------
class TestPiiScrubbing:
    from shared.pii import scrub_text

    def test_scrubs_email(self):
        from shared.pii import scrub_text
        result = scrub_text("Contact me at john.doe@example.com please.")
        assert "[email]" in result
        assert "john.doe@example.com" not in result

    def test_scrubs_phone(self):
        from shared.pii import scrub_text
        result = scrub_text("Call me on 0412 345 678 anytime.")
        assert "[phone]" in result

    def test_no_false_positive_on_plain_text(self):
        from shared.pii import scrub_text
        text = "I want to close my home loan."
        result = scrub_text(text)
        assert result == text

    def test_handles_none_gracefully(self):
        from shared.pii import scrub_text
        result = scrub_text(None)
        assert isinstance(result, str)

    def test_handles_empty_string(self):
        from shared.pii import scrub_text
        result = scrub_text("")
        assert result == ""


# ---------------------------------------------------------------------------
# shared/guardrails.py
# ---------------------------------------------------------------------------
class TestGuardrails:

    def test_detects_hardship_keyword(self):
        from shared.guardrails import detect_vulnerability
        is_vuln, keywords = detect_vulnerability("I am struggling to pay my mortgage.")
        assert is_vuln is True
        assert "struggling" in keywords

    def test_detects_bereavement_keyword(self):
        from shared.guardrails import detect_vulnerability
        is_vuln, keywords = detect_vulnerability("My spouse passed away last month.")
        assert is_vuln is True
        assert "passed away" in keywords

    def test_no_vulnerability_on_normal_note(self):
        from shared.guardrails import detect_vulnerability
        is_vuln, keywords = detect_vulnerability("I would like a payout figure for my loan.")
        assert is_vuln is False
        assert keywords == []

    def test_handles_non_string_input(self):
        from shared.guardrails import detect_vulnerability
        is_vuln, keywords = detect_vulnerability(None)
        assert is_vuln is False
        assert keywords == []

    def test_substring_evidence_guard_passes(self):
        from shared.guardrails import substring_evidence_guard
        assert substring_evidence_guard("close my loan") is True

    def test_substring_evidence_guard_fails_short(self):
        from shared.guardrails import substring_evidence_guard
        assert substring_evidence_guard("hi") is False

    def test_substring_evidence_guard_fails_empty(self):
        from shared.guardrails import substring_evidence_guard
        assert substring_evidence_guard("") is False

    def test_enforce_confidence_floors_filters_low(self):
        from shared.guardrails import enforce_confidence_floors
        hits = [
            {"rule_id": "T1", "confidence": 0.9},
            {"rule_id": "T2", "confidence": 0.3},
            {"rule_id": "T3", "confidence": 0.65},
        ]
        result = enforce_confidence_floors(hits, floor=0.6)
        assert len(result) == 2
        assert all(h["confidence"] >= 0.6 for h in result)

    def test_enforce_confidence_floors_empty_input(self):
        from shared.guardrails import enforce_confidence_floors
        assert enforce_confidence_floors([]) == []


# ---------------------------------------------------------------------------
# shared/config.py
# ---------------------------------------------------------------------------
class TestConfig:

    def test_lead_score_threshold_is_float(self):
        from shared.config import LEAD_SCORE_THRESHOLD
        assert isinstance(LEAD_SCORE_THRESHOLD, float)
        assert 0.0 < LEAD_SCORE_THRESHOLD <= 1.0

    def test_confidence_floor_is_float(self):
        from shared.config import CONFIDENCE_FLOOR
        assert isinstance(CONFIDENCE_FLOOR, float)
        assert 0.0 < CONFIDENCE_FLOOR <= 1.0

    def test_evidence_min_len_is_int(self):
        from shared.config import EVIDENCE_MIN_LEN
        assert isinstance(EVIDENCE_MIN_LEN, int)
        assert EVIDENCE_MIN_LEN >= 1

    def test_agent_version_is_string(self):
        from shared.config import AGENT_VERSION
        assert isinstance(AGENT_VERSION, str)
        assert len(AGENT_VERSION) > 0


# ---------------------------------------------------------------------------
# shared/text_matcher.py  (mocked — no live OpenAI call)
# ---------------------------------------------------------------------------
SAMPLE_RULESET = {
    "text_rules": {
        "T3_HOW_TO_CLOSE_LOAN": {
            "id": "T3",
            "description": "Asking how to close their loan and who to speak with.",
            "weight": 0.45,
            "phrase_hints": ["how do I close my loan", "process to close mortgage"],
            "negations": []
        },
        "T2_REQUEST_PAYOUT_FIGURE": {
            "id": "T2",
            "description": "Requesting a loan payout (payoff) figure.",
            "weight": 0.35,
            "phrase_hints": ["payout figure", "payoff amount"],
            "negations": []
        }
    }
}


class TestTextMatcher:

    def test_returns_rule_hits_on_success(self):
        from shared.text_matcher import match_text_rules
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = '{"rule_hits": [{"rule_id": "T3", "confidence": 0.95, "evidence_text": "close my loan", "description": "Asking how to close their loan", "explanation": "Direct match"}]}'
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.text_matcher.get_openai_client", return_value=mock_client):
            result = match_text_rules("I want to close my loan.", SAMPLE_RULESET)
        assert "rule_hits" in result
        assert isinstance(result["rule_hits"], list)

    def test_returns_empty_hits_on_openai_failure(self):
        from shared.text_matcher import match_text_rules
        with patch("shared.text_matcher.get_openai_client", side_effect=ValueError("No key")):
            result = match_text_rules("some text", SAMPLE_RULESET)
        assert result["rule_hits"] == []
        assert "error" in result

    def test_all_catalog_rules_present_in_output(self):
        """Even rules with zero confidence should appear in the output."""
        from shared.text_matcher import match_text_rules
        mock_client = MagicMock()
        mock_resp = MagicMock()
        # Only one rule returned from LLM
        mock_resp.choices[0].message.content = '{"rule_hits": [{"rule_id": "T3", "confidence": 0.95, "evidence_text": "close my loan", "description": "desc", "explanation": "match"}]}'
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.text_matcher.get_openai_client", return_value=mock_client):
            result = match_text_rules("close my loan", SAMPLE_RULESET)
        rule_ids = {h["rule_id"] for h in result["rule_hits"]}
        # Both T3 and T2 should be in output (T2 as a zero-confidence entry)
        assert "T3" in rule_ids
        assert "T2" in rule_ids

    def test_hit_flag_true_when_confidence_and_evidence_meet_threshold(self):
        from shared.text_matcher import match_text_rules
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = '{"rule_hits": [{"rule_id": "T3", "confidence": 0.95, "evidence_text": "close my loan", "description": "desc", "explanation": "match"}]}'
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.text_matcher.get_openai_client", return_value=mock_client):
            result = match_text_rules("close my loan", SAMPLE_RULESET)
        t3 = next(h for h in result["rule_hits"] if h["rule_id"] == "T3")
        assert t3["hit"] is True

    def test_hit_flag_false_when_evidence_too_short(self):
        from shared.text_matcher import match_text_rules
        mock_client = MagicMock()
        mock_resp = MagicMock()
        # Evidence is only 2 chars — should fail the evidence guard
        mock_resp.choices[0].message.content = '{"rule_hits": [{"rule_id": "T3", "confidence": 0.95, "evidence_text": "hi", "description": "desc", "explanation": "match"}]}'
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.text_matcher.get_openai_client", return_value=mock_client):
            result = match_text_rules("hi", SAMPLE_RULESET)
        t3 = next((h for h in result["rule_hits"] if h["rule_id"] == "T3"), None)
        if t3:
            assert t3["hit"] is False


# ---------------------------------------------------------------------------
# shared/rules.py — score_event
# ---------------------------------------------------------------------------
class TestScoreEvent:

    RULESET = {
        "confidence_floor": 0.6,
        "weights": {
            "tenure_risk": 0.15,
            "broker_risk": 0.10,
            "rate_delta_risk": 0.20,
            "io_expiry_risk": 0.25,
        },
        "text_rules": {
            "T3": {"weight": 0.45}
        }
    }

    def _make_text_result(self, rule_id="T3", confidence=0.9, evidence="close my loan"):
        return {
            "rule_hits": [
                {"rule_id": rule_id, "confidence": confidence,
                 "hit": True, "evidence_text": evidence,
                 "description": "Asking how to close their loan", "explanation": "match"}
            ]
        }

    def test_score_is_between_0_and_1(self):
        from shared.rules import score_event
        features = {"remaining_years": 3.0, "is_broker_originated": False,
                    "interest_rate": 4.5, "advertised_rate": 4.0,
                    "is_interest_only": False}
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            score, details = score_event(self.RULESET, self._make_text_result(), features)
        assert 0.0 <= score <= 1.0

    def test_tenure_risk_adds_to_score(self):
        from shared.rules import score_event
        features = {"remaining_years": 3.0, "is_broker_originated": False,
                    "interest_rate": 4.0, "advertised_rate": 4.0,
                    "is_interest_only": False}
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            score_with, _ = score_event(self.RULESET, {"rule_hits": []}, features)

        features_no_tenure = {**features, "remaining_years": 15.0}
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            score_without, _ = score_event(self.RULESET, {"rule_hits": []}, features_no_tenure)

        assert score_with > score_without

    def test_broker_risk_adds_to_score(self):
        from shared.rules import score_event
        features_broker = {"remaining_years": 15.0, "is_broker_originated": True,
                           "interest_rate": 4.0, "advertised_rate": 4.0,
                           "is_interest_only": False}
        features_no_broker = {**features_broker, "is_broker_originated": False}
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            score_broker, _ = score_event(self.RULESET, {"rule_hits": []}, features_broker)
            score_no_broker, _ = score_event(self.RULESET, {"rule_hits": []}, features_no_broker)
        assert score_broker > score_no_broker

    def test_rate_delta_risk_adds_to_score(self):
        from shared.rules import score_event
        features_high_rate = {"remaining_years": 15.0, "is_broker_originated": False,
                              "interest_rate": 6.5, "advertised_rate": 4.0,
                              "is_interest_only": False}
        features_normal_rate = {**features_high_rate, "interest_rate": 4.1}
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            score_high, _ = score_event(self.RULESET, {"rule_hits": []}, features_high_rate)
            score_normal, _ = score_event(self.RULESET, {"rule_hits": []}, features_normal_rate)
        assert score_high > score_normal

    def test_details_contains_required_keys(self):
        from shared.rules import score_event
        features = {"remaining_years": 3.0, "is_broker_originated": True,
                    "interest_rate": 5.0, "advertised_rate": 4.0,
                    "is_interest_only": False}
        with patch("shared.rules.get_meaningful_explanation", return_value="test summary"):
            _, details = score_event(self.RULESET, self._make_text_result(), features)
        assert "rule_hits_json" in details
        assert "explanation_text" in details
        assert "agent_version" in details

    def test_agent_version_comes_from_config(self):
        from shared.rules import score_event
        from shared.config import AGENT_VERSION
        features = {"remaining_years": 15.0, "is_broker_originated": False,
                    "interest_rate": 4.0, "advertised_rate": 4.0,
                    "is_interest_only": False}
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            _, details = score_event(self.RULESET, {"rule_hits": []}, features)
        assert details["agent_version"] == AGENT_VERSION