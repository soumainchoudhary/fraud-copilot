"""Unit and integration tests for relational persistence, multi-tenancy, and audit trail."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import CaseEntity
from app.db.repository import CaseRepository
from app.models.schemas import CaseUpdateRequest


@pytest.fixture
def in_memory_repo():
    """Create an isolated in-memory SQLite repository for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    repo = CaseRepository(session_factory=session_factory)
    return repo


class TestDatabaseAndRepository:

    def test_seed_and_query_cases(self, in_memory_repo):
        count = in_memory_repo.seed_if_empty()
        assert count > 0

        # Query first page
        cases, total = in_memory_repo.list_cases(page=1, page_size=10)
        assert len(cases) == 10
        assert total == count
        assert cases[0].case_id.startswith("CASE-")

    def test_tenant_isolation(self, in_memory_repo):
        # Insert a case in tenant A
        with in_memory_repo.get_session() as session:
            c1 = CaseEntity(
                tenant_id="tenant_alpha",
                case_id="CASE-ALPHA-01",
                transaction_id="TXN-A1",
                account_holder="Alpha Corp",
                account_number="111122223333",
                upi_id="alpha@bank",
                risk_score=0.92,
                amount=50000.0,
                status="open",
            )
            c2 = CaseEntity(
                tenant_id="tenant_beta",
                case_id="CASE-BETA-01",
                transaction_id="TXN-B1",
                account_holder="Beta LLC",
                account_number="444455556666",
                upi_id="beta@bank",
                risk_score=0.85,
                amount=25000.0,
                status="open",
            )
            session.add_all([c1, c2])
            session.commit()

        # Tenant Alpha can only see its own cases
        alpha_cases, alpha_total = in_memory_repo.list_cases(tenant_id="tenant_alpha")
        assert alpha_total == 1
        assert alpha_cases[0].case_id == "CASE-ALPHA-01"

        # Tenant Beta can only see its own cases
        beta_cases, beta_total = in_memory_repo.list_cases(tenant_id="tenant_beta")
        assert beta_total == 1
        assert beta_cases[0].case_id == "CASE-BETA-01"

        # Fetch by ID with wrong tenant returns None
        assert in_memory_repo.get_case("CASE-ALPHA-01", tenant_id="tenant_beta") is None

    def test_audit_trail_on_update(self, in_memory_repo):
        with in_memory_repo.get_session() as session:
            c = CaseEntity(
                tenant_id="default",
                case_id="CASE-AUDIT-01",
                transaction_id="TXN-AU-1",
                account_holder="Audit Subject",
                account_number="999988887777",
                upi_id="audit@upi",
                status="open",
                assigned_to="INV-100",
            )
            session.add(c)
            session.commit()

        # Update case status and notes
        update_req = CaseUpdateRequest(
            status="escalated",
            investigator_notes="Escalated due to suspicious transfer burst.",
            assigned_to="INV-L2-SPECIALIST",
        )
        updated = in_memory_repo.update_case(
            case_id="CASE-AUDIT-01",
            update=update_req,
            actor="analyst_jane",
            role="INVESTIGATOR_L2",
        )

        assert updated is not None
        assert updated.status == "escalated"
        assert updated.assigned_to == "INV-L2-SPECIALIST"
        assert "suspicious transfer burst" in updated.investigator_notes

        # Audit trail must contain entries
        trail = updated.audit_trail
        assert len(trail) >= 1
        last_event = trail[-1]
        assert last_event["action"] == "CASE_UPDATED"
        assert last_event["actor"] == "analyst_jane"
        assert last_event["role"] == "INVESTIGATOR_L2"
        assert last_event["details"]["old_status"] == "open"
        assert last_event["details"]["new_status"] == "escalated"

    def test_soft_delete(self, in_memory_repo):
        with in_memory_repo.get_session() as session:
            c = CaseEntity(
                tenant_id="default",
                case_id="CASE-DELETE-01",
                transaction_id="TXN-DEL-1",
                account_number="123412341234",
                upi_id="del@upi",
                status="open",
            )
            session.add(c)
            session.commit()

        # Soft delete
        deleted = in_memory_repo.soft_delete_case(case_id="CASE-DELETE-01", actor="admin_bob")
        assert deleted is True

        # Regular query does not find deleted case
        assert in_memory_repo.get_case("CASE-DELETE-01") is None

        # But querying with include_deleted=True finds it for compliance audit
        retained = in_memory_repo.get_case("CASE-DELETE-01", include_deleted=True)
        assert retained is not None
        assert retained.is_deleted is True
        trail = retained.audit_trail
        assert any(e["action"] == "CASE_DELETED_SOFT" for e in trail)
