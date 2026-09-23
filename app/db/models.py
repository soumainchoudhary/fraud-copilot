"""SQLAlchemy ORM models for multi-tenant enterprise case storage and audit logs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    String,
    Text,
)

from app.db.database import Base


class CaseEntity(Base):
    """Multi-tenant fraud case record with immutable audit trail and graph linkage attributes."""

    __tablename__ = "cases"

    # Multi-tenancy & Primary Keys
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, default="default", index=True)
    case_id = Column(String(64), nullable=False, unique=True, index=True)

    # Financial & Telemetry Identifiers
    transaction_id = Column(String(64), nullable=False, index=True)
    customer_id = Column(String(64), nullable=True, index=True)
    account_holder = Column(String(128), nullable=False, default="")
    account_number = Column(String(64), nullable=False, index=True)
    upi_id = Column(String(128), nullable=False, index=True)
    card_last4 = Column(String(8), nullable=False, default="")
    phone = Column(String(32), nullable=False, default="")
    email = Column(String(128), nullable=False, default="")
    address = Column(String(256), nullable=False, default="")

    # Scoring & Status
    risk_score = Column(Float, nullable=False, default=0.0)
    amount = Column(Float, nullable=False, default=0.0)
    timestamp = Column(String(64), nullable=False, default="")
    status = Column(String(32), nullable=False, default="open", index=True)
    assigned_to = Column(String(64), nullable=False, default="")

    # Investigation & Narrative
    complaint_text = Column(Text, nullable=False, default="")
    investigator_notes = Column(Text, nullable=False, default="")

    # Network Graph Links & Telemetry stored as JSON text
    _linked_accounts = Column("linked_accounts", Text, nullable=False, default="[]")
    _linked_upis = Column("linked_upis", Text, nullable=False, default="[]")
    _device_ids = Column("device_ids", Text, nullable=False, default="[]")
    _ip_addresses = Column("ip_addresses", Text, nullable=False, default="[]")
    _tags = Column("tags", Text, nullable=False, default="[]")
    _audit_trail = Column("audit_trail", Text, nullable=False, default="[]")

    # Soft-delete & Compliance
    is_deleted = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(String(64), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())
    updated_at = Column(String(64), nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())

    __table_args__ = (
        Index("ix_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_is_deleted", "tenant_id", "is_deleted"),
    )

    @property
    def linked_accounts(self) -> list[str]:
        try:
            return json.loads(self._linked_accounts or "[]")
        except Exception:
            return []

    @linked_accounts.setter
    def linked_accounts(self, val: list[str]) -> None:
        self._linked_accounts = json.dumps(val or [])

    @property
    def linked_upis(self) -> list[str]:
        try:
            return json.loads(self._linked_upis or "[]")
        except Exception:
            return []

    @linked_upis.setter
    def linked_upis(self, val: list[str]) -> None:
        self._linked_upis = json.dumps(val or [])

    @property
    def device_ids(self) -> list[str]:
        try:
            return json.loads(self._device_ids or "[]")
        except Exception:
            return []

    @device_ids.setter
    def device_ids(self, val: list[str]) -> None:
        self._device_ids = json.dumps(val or [])

    @property
    def ip_addresses(self) -> list[str]:
        try:
            return json.loads(self._ip_addresses or "[]")
        except Exception:
            return []

    @ip_addresses.setter
    def ip_addresses(self, val: list[str]) -> None:
        self._ip_addresses = json.dumps(val or [])

    @property
    def tags(self) -> list[str]:
        try:
            return json.loads(self._tags or "[]")
        except Exception:
            return []

    @tags.setter
    def tags(self, val: list[str]) -> None:
        self._tags = json.dumps(val or [])

    @property
    def audit_trail(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self._audit_trail or "[]")
        except Exception:
            return []

    @audit_trail.setter
    def audit_trail(self, val: list[dict[str, Any]]) -> None:
        self._audit_trail = json.dumps(val or [])

    def append_audit_event(self, action: str, actor: str, role: str, details: dict[str, Any] | None = None) -> None:
        """Append an immutable audit entry."""
        trail = self.audit_trail
        trail.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "actor": actor,
            "role": role,
            "details": details or {},
        })
        self.audit_trail = trail

    def to_dict(self) -> dict[str, Any]:
        """Convert entity to dictionary matching CaseItem schema."""
        return {
            "case_id": self.case_id,
            "transaction_id": self.transaction_id,
            "account_holder": self.account_holder,
            "account_number": self.account_number,
            "upi_id": self.upi_id,
            "card_last4": self.card_last4,
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "risk_score": self.risk_score,
            "amount": self.amount,
            "timestamp": self.timestamp,
            "complaint_text": self.complaint_text,
            "investigator_notes": self.investigator_notes,
            "status": self.status,
            "linked_accounts": self.linked_accounts,
            "assigned_to": self.assigned_to,
            "created_at": self.created_at,
            # Extended fields for tier-1 capabilities
            "tenant_id": self.tenant_id,
            "device_ids": self.device_ids,
            "ip_addresses": self.ip_addresses,
            "tags": self.tags,
            "audit_trail": self.audit_trail,
            "is_deleted": self.is_deleted,
            "updated_at": self.updated_at,
        }
