"""Integration tests for the Fraud Copilot API endpoints."""
from unittest.mock import patch

from fastapi.testclient import TestClient


class TestHealthEndpoint:

    def test_health_returns_ok(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestScoreEndpoint:

    def test_score_valid_transaction(self, client: TestClient, sample_transaction_dict):
        response = client.post("/score", json=sample_transaction_dict)
        assert response.status_code == 200
        data = response.json()
        assert "transaction_id" in data
        assert "risk_score" in data
        assert "flagged" in data
        assert "model_version" in data
        assert data["transaction_id"] == "TXN-TEST-001"
        assert 0.0 <= data["risk_score"] <= 1.0

    def test_score_missing_fields(self, client: TestClient):
        response = client.post("/score", json={"transaction_id": "TXN-BAD"})
        assert response.status_code == 422

    def test_score_response_model_version(self, client: TestClient, sample_transaction_dict):
        response = client.post("/score", json=sample_transaction_dict)
        data = response.json()
        assert isinstance(data["model_version"], str)
        assert len(data["model_version"]) > 0

    def test_score_batch_valid(self, client: TestClient, sample_transaction_dict):
        t1 = dict(sample_transaction_dict, transaction_id="TXN-B1")
        t2 = dict(sample_transaction_dict, transaction_id="TXN-B2", amount=999.0)
        response = client.post("/score/batch", json={"transactions": [t1, t2]})
        assert response.status_code == 200
        data = response.json()
        assert data["total_processed"] == 2
        assert len(data["results"]) == 2
        assert data["results"][0]["transaction_id"] == "TXN-B1"
        assert data["results"][1]["transaction_id"] == "TXN-B2"
        assert data["total_latency_ms"] >= 0

    def test_score_batch_empty_validation(self, client: TestClient):
        response = client.post("/score/batch", json={"transactions": []})
        assert response.status_code == 422

    def test_score_batch_limit_validation(self, client: TestClient, sample_transaction_dict):
        too_many = [dict(sample_transaction_dict, transaction_id=f"TXN-{i}") for i in range(101)]
        response = client.post("/score/batch", json={"transactions": too_many})
        assert response.status_code == 422


class TestAskEndpoint:

    @patch("app.routers.ask.retrieve")
    @patch("app.routers.ask.generate_answer")
    def test_ask_returns_answer(self, mock_generate, mock_retrieve, client: TestClient):
        mock_retrieve.return_value = [
            {
                "case_id": "CASE-001",
                "document": "Test case document",
                "score": 0.95,
                "metadata": {"risk_score": 0.9},
            }
        ]
        mock_generate.return_value = "The answer is [Case: CASE-001]."

        response = client.post("/ask", json={"query": "What cases are flagged?"})
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "sources" in data
        assert len(data["sources"]) == 1
        assert data["sources"][0]["case_id"] == "CASE-001"

    def test_ask_empty_query(self, client: TestClient):
        response = client.post("/ask", json={"query": ""})
        assert response.status_code == 422

    @patch("app.routers.ask.retrieve")
    @patch("app.routers.ask.generate_answer")
    def test_ask_with_custom_top_k(self, mock_generate, mock_retrieve, client: TestClient):
        mock_retrieve.return_value = []
        mock_generate.return_value = "No relevant cases found."

        response = client.post("/ask", json={"query": "test", "top_k": 3})
        assert response.status_code == 200
        mock_retrieve.assert_called_once_with(query="test", top_k=3)

    def test_ask_top_k_validation(self, client: TestClient):
        # top_k must be >= 1 and <= 20
        response = client.post("/ask", json={"query": "test", "top_k": 0})
        assert response.status_code == 422
        response = client.post("/ask", json={"query": "test", "top_k": 25})
        assert response.status_code == 422


class TestCasesEndpoint:

    def test_cases_stats_endpoint(self, client: TestClient):
        response = client.get("/cases/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_cases" in data
        assert "average_risk_score" in data

    def test_cases_list_endpoint(self, client: TestClient):
        response = client.get("/cases?page=1&page_size=5")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "items" in data
        assert len(data["items"]) <= 5

    def test_cases_not_found(self, client: TestClient):
        response = client.get("/cases/CASE-NONEXISTENT-9999")
        assert response.status_code == 404

    def test_cases_patch_status_and_notes(self, client: TestClient):
        list_res = client.get("/cases?page=1&page_size=1")
        assert list_res.status_code == 200
        case_id = list_res.json()["items"][0]["case_id"]

        patch_res = client.patch(
            f"/cases/{case_id}",
            json={
                "status": "escalated",
                "investigator_notes": "Urgent forensic investigation required by L2",
                "assigned_to": "INV-L2-99",
            },
        )
        assert patch_res.status_code == 200
        updated = patch_res.json()
        assert updated["case_id"] == case_id
        assert updated["status"] == "escalated"
        assert "Urgent forensic investigation required by L2" in updated["investigator_notes"]
        assert updated["assigned_to"] == "INV-L2-99"

    def test_cases_patch_invalid_status(self, client: TestClient):
        list_res = client.get("/cases?page=1&page_size=1")
        case_id = list_res.json()["items"][0]["case_id"]
        patch_res = client.patch(f"/cases/{case_id}", json={"status": "invalid_status_xyz"})
        assert patch_res.status_code == 422

    def test_cases_patch_not_found(self, client: TestClient):
        patch_res = client.patch("/cases/CASE-DOESNOTEXIST-9999", json={"status": "resolved"})
        assert patch_res.status_code == 404

    def test_cases_export_report(self, client: TestClient):
        list_res = client.get("/cases?page=1&page_size=1")
        case_id = list_res.json()["items"][0]["case_id"]
        export_res = client.get(f"/cases/{case_id}/export")
        assert export_res.status_code == 200
        assert "attachment" in export_res.headers.get("Content-Disposition", "")
        data = export_res.json()
        assert data["report_type"] == "FORENSIC_FRAUD_INCIDENT_DOSSIER"
        assert data["case_metadata"]["case_id"] == case_id
        assert "entity_details" in data
        assert "financial_telemetry" in data
        assert "investigation_trail" in data

    def test_cases_export_not_found(self, client: TestClient):
        export_res = client.get("/cases/CASE-DOESNOTEXIST-9999/export")
        assert export_res.status_code == 404

    def test_dashboard_served(self, client: TestClient):
        response = client.get("/")
        assert response.status_code == 200
        assert "Fraud Copilot" in response.text


class TestMetricsEndpoint:

    def test_metrics_accessible_publicly(self, client: TestClient):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")
        text = response.text
        assert "fraud_transactions_scored_total" in text
        assert "fraud_scoring_latency_seconds_sum" in text
        assert "fraud_rag_queries_total" in text
        assert "fraud_rate_limit_rejections_total" in text
        assert "fraud_cases_updated_total" in text

    def test_metrics_counter_increments(self, client: TestClient, sample_transaction_dict):
        # 1. Score a transaction
        client.post("/score", json=sample_transaction_dict)
        # 2. Check metrics output
        res = client.get("/metrics")
        assert res.status_code == 200
        assert "fraud_transactions_scored_total" in res.text


