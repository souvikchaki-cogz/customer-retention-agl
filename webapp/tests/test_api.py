"""
Unit tests for the FastAPI webapp (webapp/app/main.py).

Run from project root:
    pytest webapp/tests/test_api.py -v
"""
import sys
import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from fastapi.testclient import TestClient
from webapp.app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------
class TestHealthEndpoint:

    def test_health_returns_ok(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /api/evaluate
# ---------------------------------------------------------------------------
class TestEvaluateEndpoint:

    VALID_PAYLOAD = {"customer_id": "CUST0001", "note": "I want to cancel my electricity account and get a final meter read."}

    def test_evaluate_returns_evaluate_response_shape(self):
        mock_start_resp = {
            "id": "instance-abc-123",
            "statusQueryGetUri": "http://localhost:7071/status/instance-abc-123"
        }
        mock_status_resp = {
            "runtimeStatus": "Running",
            "customStatus": {"progress": 10, "status": "started"}
        }
        with patch("webapp.app.main._call_function_start",
                   new_callable=AsyncMock, return_value=mock_start_resp), \
             patch("webapp.app.main._call_status",
                   new_callable=AsyncMock, return_value=mock_status_resp):
            response = client.post("/api/evaluate", json=self.VALID_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert data["customer_id"] == "CUST0001"
        assert data["instance_id"] == "instance-abc-123"
        assert "status_query_url" in data

    def test_evaluate_missing_customer_id_returns_422(self):
        response = client.post("/api/evaluate", json={"note": "some note"})
        assert response.status_code == 422

    def test_evaluate_missing_note_returns_422(self):
        response = client.post("/api/evaluate", json={"customer_id": "CUST001"})
        assert response.status_code == 422

    def test_evaluate_function_start_failure_returns_500(self):
        with patch("webapp.app.main._call_function_start",
                   new_callable=AsyncMock, side_effect=Exception("Function down")):
            response = client.post("/api/evaluate", json=self.VALID_PAYLOAD)
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/evaluate/status/{instance_id}
# ---------------------------------------------------------------------------
class TestEvaluateStatusEndpoint:

    def test_status_unknown_instance_returns_404(self):
        response = client.get("/api/evaluate/status/nonexistent-instance")
        assert response.status_code == 404

    def test_status_known_instance_returns_status(self):
        # Seed the in-memory dict via an evaluate call first
        mock_start_resp = {
            "id": "instance-status-test",
            "statusQueryGetUri": "http://localhost:7071/status/instance-status-test"
        }
        mock_status_resp = {
            "runtimeStatus": "Completed",
            "customStatus": {"progress": 100, "status": "complete",
                             "result": {"score": 0.85, "should_emit": True}}
        }
        with patch("webapp.app.main._call_function_start",
                   new_callable=AsyncMock, return_value=mock_start_resp), \
             patch("webapp.app.main._call_status",
                   new_callable=AsyncMock, return_value=mock_status_resp):
            client.post("/api/evaluate", json={"customer_id": "CUST001", "note": "test"})

        with patch("webapp.app.main._call_status",
                   new_callable=AsyncMock, return_value=mock_status_resp):
            response = client.get("/api/evaluate/status/instance-status-test")

        assert response.status_code == 200
        data = response.json()
        assert data["instance_id"] == "instance-status-test"
        assert data["runtime_status"] == "Completed"
        assert data["result"]["score"] == 0.85


# ---------------------------------------------------------------------------
# POST /api/predict
# ---------------------------------------------------------------------------
class TestPredictEndpoint:

    MOCK_TRIGGERS = [
        {
            "description": "Move-Out Intent",
            "example_phrases": "final meter read, moving house, close my account, selling the property",
            "narrative_explanation": "Customers requesting final meter reads or mentioning a property sale are near-certain churners. Without a seamless account transfer offer, these customers are lost by default.",
            "support": {"value": 0.18, "explanation": "18% of at-risk customers show move-out signals."},
            "lift": {"value": 4.2, "explanation": "4.2x more likely to churn than the average customer."},
            "odds_ratio": {"value": 6.1, "explanation": "6.1x higher odds of account closure."},
            "p_value": 0.0001,
            "fdr": 0.0002
        }
    ]

    def test_predict_returns_triggers(self):
        with patch("webapp.app.main.generate_triggers", return_value=self.MOCK_TRIGGERS):
            response = client.post("/api/predict")
        assert response.status_code == 200
        data = response.json()
        assert "triggers" in data
        assert len(data["triggers"]) == 1
        assert data["triggers"][0]["description"] == "Move-Out Intent"

    def test_predict_failure_returns_500(self):
        with patch("webapp.app.main.generate_triggers", side_effect=Exception("OpenAI down")):
            response = client.post("/api/predict")
        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/triggers
# ---------------------------------------------------------------------------
class TestGetTriggersEndpoint:

    def test_get_triggers_returns_list(self):
        mock_rows = [
            {"id": 1, "phrase": "Customer requesting final meter read ahead of moving out", "severity": "HIGH"},
            {"id": 2, "phrase": "Customer actively comparing energy retailers", "severity": "HIGH"},
        ]
        with patch("webapp.app.main.fetch_existing_triggers", return_value=mock_rows):
            response = client.get("/api/triggers")
        assert response.status_code == 200
        data = response.json()
        assert "triggers" in data
        assert len(data["triggers"]) == 2

    def test_get_triggers_empty_returns_empty_list(self):
        with patch("webapp.app.main.fetch_existing_triggers", return_value=[]):
            response = client.get("/api/triggers")
        assert response.status_code == 200
        assert response.json()["triggers"] == []


# ---------------------------------------------------------------------------
# POST /api/triggers/approve
# ---------------------------------------------------------------------------
class TestApproveEndpoint:

    VALID_APPROVE_PAYLOAD = {
        "phrase": "Customer asking about contract exit and cooling off period",
        "example_phrases": "cooling off period, how do I exit my contract, switching retailer",
        "support": 0.15,
        "lift": 2.5,
        "odds_ratio": 3.5,
        "p_value": 0.005,
        "fdr": 0.008
    }

    def test_approve_trigger_success(self):
        with patch("webapp.app.main.update_rules_library_with_new_trigger", return_value=True):
            response = client.post("/api/triggers/approve", json=self.VALID_APPROVE_PAYLOAD)
        assert response.status_code == 200
        data = response.json()
        assert data["phrase"] == "Customer asking about contract exit and cooling off period"
        assert data["inserted"] is True
        assert data["severity"] in ("HIGH", "MEDIUM", "LOW")

    def test_approve_trigger_db_failure_returns_response_with_inserted_false(self):
        with patch("webapp.app.main.update_rules_library_with_new_trigger", return_value=False):
            response = client.post("/api/triggers/approve", json=self.VALID_APPROVE_PAYLOAD)
        assert response.status_code == 200
        assert response.json()["inserted"] is False

    def test_approve_trigger_high_severity_classification(self):
        """p<0.01, fdr<0.02, lift>=2 => HIGH"""
        payload = {**self.VALID_APPROVE_PAYLOAD,
                   "p_value": 0.005, "fdr": 0.01, "lift": 2.5, "odds_ratio": 4.0}
        with patch("webapp.app.main.update_rules_library_with_new_trigger", return_value=True):
            response = client.post("/api/triggers/approve", json=payload)
        assert response.json()["severity"] == "HIGH"

    def test_approve_trigger_low_severity_classification(self):
        """High p-value and low lift => LOW"""
        payload = {**self.VALID_APPROVE_PAYLOAD,
                   "p_value": 0.2, "fdr": 0.3, "lift": 1.1, "odds_ratio": 1.2}
        with patch("webapp.app.main.update_rules_library_with_new_trigger", return_value=True):
            response = client.post("/api/triggers/approve", json=payload)
        assert response.json()["severity"] == "LOW"

    def test_approve_missing_field_returns_422(self):
        payload = {k: v for k, v in self.VALID_APPROVE_PAYLOAD.items() if k != "phrase"}
        response = client.post("/api/triggers/approve", json=payload)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/triggers/{trigger_id}
# ---------------------------------------------------------------------------
class TestDeleteTriggerEndpoint:

    def test_delete_trigger_success(self):
        with patch("webapp.app.main.delete_trigger", return_value=True):
            response = client.delete("/api/triggers/42")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 42
        assert data["deleted"] is True

    def test_delete_trigger_not_found(self):
        with patch("webapp.app.main.delete_trigger", return_value=False):
            response = client.delete("/api/triggers/999")
        assert response.status_code == 200
        assert response.json()["deleted"] is False

    def test_delete_trigger_invalid_id_returns_422(self):
        response = client.delete("/api/triggers/not-a-number")
        assert response.status_code == 422