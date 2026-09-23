"""WebSocket real-time event streaming and live transaction simulation router."""
from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["streaming"])


class StreamManager:
    """Thread-safe WebSocket client connection hub."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        logger.info("websocket_client_connected", total_clients=len(self.active_connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        logger.info("websocket_client_disconnected", total_clients=len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast payload to all connected WebSocket clients."""
        payload_str = json.dumps(message)
        dead_connections = []

        async with self._lock:
            clients = list(self.active_connections)

        for ws in clients:
            try:
                await ws.send_text(payload_str)
            except Exception:
                dead_connections.append(ws)

        if dead_connections:
            async with self._lock:
                for dead in dead_connections:
                    if dead in self.active_connections:
                        self.active_connections.remove(dead)


# Global singleton stream manager
stream_manager = StreamManager()


@router.websocket("/ws/live-transactions")
async def websocket_live_transactions(websocket: WebSocket):
    """Real-time WebSocket endpoint streaming scored transactions and fraud alerts."""
    await stream_manager.connect(websocket)
    # Send initial welcome / handshake event
    try:
        await websocket.send_text(json.dumps({
            "event": "CONNECTED",
            "message": "Connected to Tier-1 Live Fraud Copilot Transaction Stream",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        while True:
            # Keep socket alive and respond to client pings
            data = await websocket.receive_text()
            if data.strip().lower() == "ping":
                await websocket.send_text(json.dumps({"event": "PONG", "timestamp": datetime.now(timezone.utc).isoformat()}))
    except WebSocketDisconnect:
        await stream_manager.disconnect(websocket)
    except Exception as e:
        logger.warning("websocket_session_error", error=str(e))
        await stream_manager.disconnect(websocket)


class SimulateStreamRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=50, description="Number of transactions to generate")
    delay_ms: int = Field(default=100, ge=0, le=2000, description="Delay between events in milliseconds")
    high_risk_ratio: float = Field(default=0.4, ge=0.0, le=1.0, description="Target probability of high-risk transactions")


@router.post("/scoring/simulate-stream")
async def simulate_transaction_stream(body: SimulateStreamRequest = SimulateStreamRequest()):
    """Development utility to emit simulated transactions and high-risk alerts over WebSockets."""
    accounts = ["051204618723", "382675869261", "991204128491", "441092837192", "882104928172"]
    upis = ["sudiksha01@ibl", "narayangirin@ibl", "paytm-user@ybl", "merchant@okaxis", "alex99@oksbi"]
    merchants = ["Jacobson Ltd", "Alvarado, Rangel and Collins", "Amazon Web Services", "Apple Store NYC", "Crypto OTC Exchange"]

    generated = []

    for i in range(body.count):
        is_high_risk = random.random() < body.high_risk_ratio
        risk_score = round(random.uniform(0.78, 0.99) if is_high_risk else random.uniform(0.01, 0.35), 4)
        amount = round(random.uniform(5000.0, 150000.0) if is_high_risk else random.uniform(10.0, 1200.0), 2)
        txn_id = f"TXN-SIM-{uuid.uuid4().hex[:8].upper()}"

        event_payload = {
            "event": "TRANSACTION_SCORED",
            "transaction_id": txn_id,
            "account_number": random.choice(accounts),
            "upi_id": random.choice(upis),
            "merchant": random.choice(merchants),
            "amount": amount,
            "risk_score": risk_score,
            "flagged": risk_score >= 0.5,
            "alert_level": "CRITICAL" if risk_score >= 0.85 else ("WARNING" if risk_score >= 0.5 else "LOW"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        generated.append(event_payload)
        await stream_manager.broadcast(event_payload)

        if body.delay_ms > 0 and i < body.count - 1:
            await asyncio.sleep(body.delay_ms / 1000.0)

    return {
        "status": "stream_simulated",
        "events_emitted": len(generated),
        "active_subscribers": len(stream_manager.active_connections),
        "events": generated,
    }
