"""Tests for WebSocket live transaction streaming and simulation."""
import json

from fastapi.testclient import TestClient


class TestStreamingAndWebSockets:

    def test_websocket_connect_and_heartbeat(self, client: TestClient):
        with client.websocket_connect("/ws/live-transactions") as websocket:
            # 1. Handshake welcome
            initial = websocket.receive_text()
            data = json.loads(initial)
            assert data["event"] == "CONNECTED"
            assert "Live Fraud Copilot" in data["message"]

            # 2. Ping / Pong
            websocket.send_text("ping")
            pong = websocket.receive_text()
            pong_data = json.loads(pong)
            assert pong_data["event"] == "PONG"

    def test_simulate_stream_endpoint(self, client: TestClient):
        res = client.post(
            "/scoring/simulate-stream",
            json={"count": 3, "delay_ms": 10, "high_risk_ratio": 0.5},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "stream_simulated"
        assert data["events_emitted"] == 3
        assert len(data["events"]) == 3
        assert data["events"][0]["event"] == "TRANSACTION_SCORED"
        assert "risk_score" in data["events"][0]
