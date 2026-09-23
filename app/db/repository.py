"""Data access layer for fraud cases, audit logs, and multi-tenant isolation."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.database import get_session_factory, init_db
from app.db.models import CaseEntity
from app.models.schemas import CaseStatsResponse, CaseUpdateRequest

logger = structlog.get_logger(__name__)


class CaseRepository:
    """Enterprise repository for fraud cases with multi-tenant filtering and audit trails."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or get_session_factory()

    def get_session(self) -> Session:
        return self.session_factory()

    def seed_if_empty(self, seed_file: str | Path = "data/synthetic_cases.json") -> int:
        """Seed the relational database from synthetic cases JSON if empty."""
        init_db()
        path = Path(seed_file)
        if not path.exists():
            logger.warning("seed_file_not_found", path=str(path))
            return 0

        with self.get_session() as session:
            count = session.query(func.count(CaseEntity.id)).scalar() or 0
            if count > 0:
                logger.info("database_already_seeded", count=count)
                return count

            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw_cases = json.load(f)
            except Exception as e:
                logger.error("failed_reading_seed_cases", error=str(e))
                return 0

            entities = []
            for item in raw_cases:
                # Deterministically synthesize device IDs & IPs based on account number and UPI for rich graph linkages
                acc = item.get("account_number", "")
                upi = item.get("upi_id", "")
                h = hashlib.sha256(f"{acc}:{upi}".encode()).hexdigest()
                dev_id = f"DEV-{h[:8].upper()}"
                ip_addr = f"192.168.{(int(h[8:10], 16) % 254) + 1}.{(int(h[10:12], 16) % 254) + 1}"

                entity = CaseEntity(
                    tenant_id="default",
                    case_id=item.get("case_id"),
                    transaction_id=item.get("transaction_id"),
                    customer_id=item.get("customer_id") or f"CUST-{item.get('card_last4', '0000')}",
                    account_holder=item.get("account_holder", ""),
                    account_number=acc,
                    upi_id=upi,
                    card_last4=item.get("card_last4", ""),
                    phone=item.get("phone", ""),
                    email=item.get("email", ""),
                    address=item.get("address", ""),
                    risk_score=float(item.get("risk_score", 0.0)),
                    amount=float(item.get("amount", 0.0)),
                    timestamp=item.get("timestamp", ""),
                    complaint_text=item.get("complaint_text", ""),
                    investigator_notes=item.get("investigator_notes", ""),
                    status=item.get("status", "open"),
                    assigned_to=item.get("assigned_to", "INV-UNASSIGNED"),
                    created_at=item.get("created_at", datetime.now(timezone.utc).isoformat()),
                    updated_at=item.get("created_at", datetime.now(timezone.utc).isoformat()),
                    is_deleted=False,
                )
                entity.linked_accounts = item.get("linked_accounts", [])
                entity.device_ids = [dev_id]
                entity.ip_addresses = [ip_addr]
                entity.tags = ["synthetic", "initial_seed"]
                entity.append_audit_event(
                    action="SEEDED",
                    actor="system",
                    role="ADMIN",
                    details={"source": str(path)},
                )
                entities.append(entity)

            session.add_all(entities)
            session.commit()
            logger.info("database_seeded_successfully", count=len(entities))
            return len(entities)

    def get_case(
        self,
        case_id: str,
        tenant_id: str = "default",
        include_deleted: bool = False,
    ) -> CaseEntity | None:
        """Fetch a single case by case_id within tenant isolation boundary."""
        with self.get_session() as session:
            query = session.query(CaseEntity).filter(
                func.upper(CaseEntity.case_id) == case_id.strip().upper(),
                CaseEntity.tenant_id == tenant_id,
            )
            if not include_deleted:
                query = query.filter(CaseEntity.is_deleted.is_(False))
            return query.first()

    def list_cases(
        self,
        tenant_id: str = "default",
        status: Optional[str] = None,
        search: Optional[str] = None,
        min_risk: Optional[float] = None,
        page: int = 1,
        page_size: int = 20,
        include_deleted: bool = False,
    ) -> tuple[list[CaseEntity], int]:
        """List cases with multi-tenant filtering, pagination, and total count."""
        with self.get_session() as session:
            query = session.query(CaseEntity).filter(CaseEntity.tenant_id == tenant_id)
            if not include_deleted:
                query = query.filter(CaseEntity.is_deleted.is_(False))

            if status and status.lower() != "all":
                query = query.filter(func.lower(CaseEntity.status) == status.strip().lower())

            if min_risk is not None:
                query = query.filter(CaseEntity.risk_score >= min_risk)

            if search:
                s = f"%{search.strip().lower()}%"
                query = query.filter(
                    or_(
                        func.lower(CaseEntity.case_id).like(s),
                        func.lower(CaseEntity.account_holder).like(s),
                        func.lower(CaseEntity.account_number).like(s),
                        func.lower(CaseEntity.upi_id).like(s),
                    )
                )

            total = query.count()
            offset = max(0, (page - 1) * page_size)
            items = query.order_by(CaseEntity.risk_score.desc()).offset(offset).limit(page_size).all()
            return items, total

    def update_case(
        self,
        case_id: str,
        update: CaseUpdateRequest,
        actor: str = "system",
        role: str = "ANALYST_L1",
        tenant_id: str = "default",
    ) -> CaseEntity | None:
        """Update case record with status/notes and append immutable audit log."""
        with self.get_session() as session:
            entity = session.query(CaseEntity).filter(
                func.upper(CaseEntity.case_id) == case_id.strip().upper(),
                CaseEntity.tenant_id == tenant_id,
                CaseEntity.is_deleted.is_(False),
            ).first()

            if not entity:
                return None

            diff: dict[str, Any] = {}
            if update.status and update.status != entity.status:
                diff["old_status"] = entity.status
                diff["new_status"] = update.status
                entity.status = update.status

            if update.assigned_to and update.assigned_to != entity.assigned_to:
                diff["old_assigned_to"] = entity.assigned_to
                diff["new_assigned_to"] = update.assigned_to
                entity.assigned_to = update.assigned_to

            if update.investigator_notes:
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                new_note = f"[{now_str}] {update.investigator_notes.strip()}"
                diff["note_appended"] = new_note
                existing = entity.investigator_notes
                if existing:
                    entity.investigator_notes = f"{existing} | {new_note}"
                else:
                    entity.investigator_notes = new_note

            entity.updated_at = datetime.now(timezone.utc).isoformat()
            entity.append_audit_event(
                action="CASE_UPDATED",
                actor=actor,
                role=role,
                details=diff,
            )

            session.commit()
            session.refresh(entity)
            return entity

    def soft_delete_case(
        self,
        case_id: str,
        actor: str = "admin",
        role: str = "ADMIN",
        tenant_id: str = "default",
    ) -> bool:
        """Soft-delete a case record while preserving compliance audit history."""
        with self.get_session() as session:
            entity = session.query(CaseEntity).filter(
                func.upper(CaseEntity.case_id) == case_id.strip().upper(),
                CaseEntity.tenant_id == tenant_id,
                CaseEntity.is_deleted.is_(False),
            ).first()

            if not entity:
                return False

            entity.is_deleted = True
            entity.updated_at = datetime.now(timezone.utc).isoformat()
            entity.append_audit_event(
                action="CASE_DELETED_SOFT",
                actor=actor,
                role=role,
                details={"reason": "Admin soft delete request"},
            )
            session.commit()
            return True

    def get_case_stats(self, tenant_id: str = "default") -> CaseStatsResponse:
        """Compute aggregated status and risk metrics across non-deleted cases."""
        with self.get_session() as session:
            base_q = session.query(CaseEntity).filter(
                CaseEntity.tenant_id == tenant_id,
                CaseEntity.is_deleted.is_(False),
            )

            total = base_q.count()
            if total == 0:
                return CaseStatsResponse(
                    total_cases=0,
                    open_cases=0,
                    escalated_cases=0,
                    under_review_cases=0,
                    resolved_cases=0,
                    average_risk_score=0.0,
                )

            open_count = base_q.filter(CaseEntity.status == "open").count()
            escalated_count = base_q.filter(CaseEntity.status == "escalated").count()
            under_review_count = base_q.filter(CaseEntity.status == "under_review").count()
            resolved_count = base_q.filter(CaseEntity.status.in_(["resolved", "closed"])).count()

            avg_risk = session.query(func.avg(CaseEntity.risk_score)).filter(
                CaseEntity.tenant_id == tenant_id,
                CaseEntity.is_deleted.is_(False),
            ).scalar() or 0.0

            return CaseStatsResponse(
                total_cases=total,
                open_cases=open_count,
                escalated_cases=escalated_count,
                under_review_cases=under_review_count,
                resolved_cases=resolved_count,
                average_risk_score=round(float(avg_risk), 4),
            )

    def get_all_active_cases_dict(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        """Return all active non-deleted cases as dicts (for graph and retrieval indexing)."""
        with self.get_session() as session:
            entities = session.query(CaseEntity).filter(
                CaseEntity.tenant_id == tenant_id,
                CaseEntity.is_deleted.is_(False),
            ).all()
            return [e.to_dict() for e in entities]


# Singleton instance
repository = CaseRepository()
