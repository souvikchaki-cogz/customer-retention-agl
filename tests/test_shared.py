"""
Unit tests for shared/* modules (guardrails, pii, config, text_matcher, rules).

Run from project root:
    pytest tests/test_shared.py -v
"""
import sys
import os
import pytest
from datetime import datetime, timezone, timedelta
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
        text = "I want to cancel my electricity account."
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
        is_vuln, keywords = detect_vulnerability("I am struggling to pay my energy bill.")
        assert is_vuln is True
        assert "struggling" in keywords

    def test_detects_bereavement_keyword(self):
        from shared.guardrails import detect_vulnerability
        is_vuln, keywords = detect_vulnerability("My spouse passed away last month.")
        assert is_vuln is True
        assert "passed away" in keywords

    def test_no_vulnerability_on_normal_note(self):
        from shared.guardrails import detect_vulnerability
        is_vuln, keywords = detect_vulnerability("I would like to know my contract end date.")
        assert is_vuln is False
        assert keywords == []

    def test_handles_non_string_input(self):
        from shared.guardrails import detect_vulnerability
        is_vuln, keywords = detect_vulnerability(None)
        assert is_vuln is False
        assert keywords == []

    def test_detects_life_support_keyword(self):
        from shared.guardrails import detect_life_support
        assert detect_life_support("My husband is on life support at home.") is True

    def test_detect_life_support_returns_false_on_normal_note(self):
        from shared.guardrails import detect_life_support
        assert detect_life_support("What is my current plan?") is False

    def test_substring_evidence_guard_passes(self):
        from shared.guardrails import substring_evidence_guard
        assert substring_evidence_guard("cancel my electricity") is True

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
        "T2_MOVE_OUT_REQUEST": {
            "id": "T2",
            "description": "Customer explicitly stating they are moving out of the property.",
            "weight": 0.55,
            "phrase_hints": ["moving out", "moving house", "selling the house"],
            "negations": []
        },
        "T7_COMPARING_RETAILERS": {
            "id": "T7",
            "description": "Customer actively comparing AGL against other energy retailers.",
            "weight": 0.45,
            "phrase_hints": ["shopping around", "comparing retailers", "found a cheaper plan"],
            "negations": ["energy made easy account"]
        }
    }
}


class TestTextMatcher:

    def test_returns_rule_hits_on_success(self):
        from shared.text_matcher import match_text_rules
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = '{"rule_hits": [{"rule_id": "T2", "confidence": 0.95, "evidence_text": "moving house", "description": "Customer explicitly stating they are moving out of the property.", "explanation": "Direct match"}]}'
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.text_matcher.get_openai_client", return_value=mock_client):
            result = match_text_rules("I am moving house next month.", SAMPLE_RULESET)
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
        mock_resp.choices[0].message.content = '{"rule_hits": [{"rule_id": "T2", "confidence": 0.95, "evidence_text": "moving house", "description": "desc", "explanation": "match"}]}'
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.text_matcher.get_openai_client", return_value=mock_client):
            result = match_text_rules("moving house", SAMPLE_RULESET)
        rule_ids = {h["rule_id"] for h in result["rule_hits"]}
        # Both T2 and T7 should be in output (T7 as a zero-confidence entry)
        assert "T2" in rule_ids
        assert "T7" in rule_ids

    def test_hit_flag_true_when_confidence_and_evidence_meet_threshold(self):
        from shared.text_matcher import match_text_rules
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = '{"rule_hits": [{"rule_id": "T7", "confidence": 0.95, "evidence_text": "shopping around", "description": "Customer actively comparing AGL against other energy retailers.", "explanation": "match"}]}'
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.text_matcher.get_openai_client", return_value=mock_client):
            result = match_text_rules("shopping around", SAMPLE_RULESET)
        t7 = next(h for h in result["rule_hits"] if h["rule_id"] == "T7")
        assert t7["hit"] is True

    def test_hit_flag_false_when_evidence_too_short(self):
        from shared.text_matcher import match_text_rules
        mock_client = MagicMock()
        mock_resp = MagicMock()
        # Evidence is only 2 chars — should fail the evidence guard
        mock_resp.choices[0].message.content = '{"rule_hits": [{"rule_id": "T7", "confidence": 0.95, "evidence_text": "hi", "description": "desc", "explanation": "match"}]}'
        mock_resp.usage = None
        mock_client.chat.completions.create.return_value = mock_resp
        with patch("shared.text_matcher.get_openai_client", return_value=mock_client):
            result = match_text_rules("hi", SAMPLE_RULESET)
        t7 = next((h for h in result["rule_hits"] if h["rule_id"] == "T7"), None)
        if t7:
            assert t7["hit"] is False


# ---------------------------------------------------------------------------
# shared/rules.py — score_event
# ---------------------------------------------------------------------------
class TestScoreEvent:

    RULESET = {
        "confidence_floor": 0.55,
        "weights": {
            "property_sale_risk": 0.35,
            "contract_expiry_risk": 0.20,
            "bill_shock_risk": 0.20,
            "no_concession_risk": 0.15,
        },
        "text_rules": {
            "T7": {"weight": 0.45}
        }
    }

    def _make_text_result(self, rule_id="T7", confidence=0.9, evidence="shopping around"):
        return {
            "rule_hits": [
                {"rule_id": rule_id, "confidence": confidence,
                 "hit": True, "evidence_text": evidence,
                 "description": "Customer actively comparing AGL against other energy retailers.",
                 "explanation": "match"}
            ]
        }

    def test_score_is_between_0_and_1(self):
        from shared.rules import score_event
        features = {
            "property_listing_status": "FOR_SALE",
            "contract_end_date": None,
            "last_bill_amount": None,
            "prev_bill_amount": None,
            "conditional_discount_removed": False,
        }
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            score, details = score_event(self.RULESET, self._make_text_result(), features)
        assert 0.0 <= score <= 1.0

    def test_property_listing_adds_to_score(self):
        from shared.rules import score_event
        features_for_sale = {
            "property_listing_status": "FOR_SALE",
            "contract_end_date": None,
            "last_bill_amount": None,
            "prev_bill_amount": None,
            "conditional_discount_removed": False,
        }
        features_no_listing = {**features_for_sale, "property_listing_status": None}
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            score_with, _ = score_event(self.RULESET, {"rule_hits": []}, features_for_sale)
            score_without, _ = score_event(self.RULESET, {"rule_hits": []}, features_no_listing)
        assert score_with > score_without

    def test_contract_expiry_adds_to_score(self):
        from shared.rules import score_event
        contract_date = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
        features_expiring = {
            "property_listing_status": None,
            "contract_end_date": contract_date,
            "last_bill_amount": None,
            "prev_bill_amount": None,
            "conditional_discount_removed": False,
        }
        features_no_expiry = {**features_expiring, "contract_end_date": None}
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            score_with, _ = score_event(self.RULESET, {"rule_hits": []}, features_expiring)
            score_without, _ = score_event(self.RULESET, {"rule_hits": []}, features_no_expiry)
        assert score_with > score_without

    def test_bill_shock_adds_to_score(self):
        from shared.rules import score_event
        features_high_bill = {
            "property_listing_status": None,
            "contract_end_date": None,
            "last_bill_amount": 500,
            "prev_bill_amount": 300,
            "conditional_discount_removed": False,
        }
        features_normal_bill = {**features_high_bill, "last_bill_amount": 310}
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            score_high, _ = score_event(self.RULESET, {"rule_hits": []}, features_high_bill)
            score_normal, _ = score_event(self.RULESET, {"rule_hits": []}, features_normal_bill)
        assert score_high > score_normal

    def test_details_contains_required_keys(self):
        from shared.rules import score_event
        features = {
            "property_listing_status": "FOR_SALE",
            "contract_end_date": None,
            "last_bill_amount": 500,
            "prev_bill_amount": 300,
            "conditional_discount_removed": False,
        }
        with patch("shared.rules.get_meaningful_explanation", return_value="test summary"):
            _, details = score_event(self.RULESET, self._make_text_result(), features)
        assert "rule_hits_json" in details
        assert "explanation_text" in details
        assert "agent_version" in details

    def test_agent_version_comes_from_config(self):
        from shared.rules import score_event
        from shared.config import AGENT_VERSION
        features = {
            "property_listing_status": None,
            "contract_end_date": None,
            "last_bill_amount": None,
            "prev_bill_amount": None,
            "conditional_discount_removed": False,
        }
        with patch("shared.rules.get_meaningful_explanation", return_value="summary"):
            _, details = score_event(self.RULESET, {"rule_hits": []}, features)
        assert details["agent_version"] == AGENT_VERSION