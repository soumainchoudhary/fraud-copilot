"""Case management endpoints backed by multi-tenant repository, entity graphs, and SAR compliance."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import Path as FastAPIPath

from app.compliance.sar_generator import generate_sar_dossier, generate_sar_xml
from app.db.repository import repository
from app.graph.graph_service import get_graph_service
from app.metrics import metrics
from app.models.schemas import (
    CaseItem,
    CaseListResponse,
    CaseStatsResponse,
    CaseUpdateRequest,
)
from app.security.rbac import UserRole, get_current_role, require_role

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/cases", tags=["cases"])


def _load_cases() -> list[dict]:
    """Backward-compatible loader delegating to the enterprise repository."""
    # Ensure seeded
    repository.seed_if_empty()
    return repository.get_all_active_cases_dict()


@router.get("/stats", response_model=CaseStatsResponse)
def get_case_stats(
    tenant_id: str = Query("default", description="Tenant ID"),
    current_role: str = Depends(get_current_role),
) -> CaseStatsResponse:
    """Get aggregated statistics across active case records within tenant."""
    _load_cases()
    return repository.get_case_stats(tenant_id=tenant_id)


@router.get("", response_model=CaseListResponse)
def list_cases(
    status: Optional[str] = Query(None, description="Filter by status (open, escalated, under_review, resolved)"),
    search: Optional[str] = Query(None, description="Search by case ID, account, UPI, or customer name"),
    min_risk: Optional[float] = Query(None, ge=0.0, le=1.0, description="Filter cases with risk >= min_risk"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    tenant_id: str = Query("default", description="Tenant ID for multi-tenant isolation"),
    current_role: str = Depends(get_current_role),
) -> CaseListResponse:
    """List and filter fraud cases with pagination and multi-tenant isolation."""
    # Normalize query params when invoked directly in Python
    status_str = status if isinstance(status, str) else None
    search_str = search if isinstance(search, str) else None
    min_risk_val = min_risk if isinstance(min_risk, (int, float)) else None
    page_val = page if isinstance(page, int) else 1
    page_size_val = page_size if isinstance(page_size, int) else 20
    tenant_str = tenant_id if isinstance(tenant_id, str) else "default"

    entities, total = repository.list_cases(
        tenant_id=tenant_str,
        status=status_str,
        search=search_str,
        min_risk=min_risk_val,
        page=page_val,
        page_size=page_size_val,
    )

    items = [CaseItem(**e.to_dict()) for e in entities]
    return CaseListResponse(
        total=total,
        page=page_val,
        page_size=page_size_val,
        items=items,
    )


@router.get("/{case_id}", response_model=CaseItem)
def get_case(
    case_id: str = FastAPIPath(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$", description="Valid alphanumeric Case ID"),
    tenant_id: str = Query("default", description="Tenant ID"),
    current_role: str = Depends(get_current_role),
) -> CaseItem:
    """Retrieve details for a single case by ID."""
    entity = repository.get_case(case_id=case_id, tenant_id=tenant_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return CaseItem(**entity.to_dict())


@router.patch("/{case_id}", response_model=CaseItem)
def update_case(
    case_id: str = FastAPIPath(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$", description="Valid alphanumeric Case ID"),
    update: CaseUpdateRequest = ...,
    tenant_id: str = Query("default", description="Tenant ID"),
    current_role: str = Depends(get_current_role),
) -> CaseItem:
    """Update case status, assignment, or append timestamped investigator notes."""
    entity = repository.update_case(
        case_id=case_id,
        update=update,
        actor=f"user-{current_role.lower()}",
        role=current_role,
        tenant_id=tenant_id,
    )
    if not entity:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    metrics.inc_case_update()
    logger.info(
        "case_updated",
        case_id=entity.case_id,
        status=entity.status,
        assigned_to=entity.assigned_to,
        role=current_role,
    )
    return CaseItem(**entity.to_dict())


@router.delete("/{case_id}", dependencies=[Depends(require_role(UserRole.ADMIN))])
def delete_case(
    case_id: str = FastAPIPath(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$", description="Valid alphanumeric Case ID"),
    tenant_id: str = Query("default", description="Tenant ID"),
    current_role: str = Depends(get_current_role),
):
    """Soft-delete a case record (Admin privileged operation)."""
    success = repository.soft_delete_case(
        case_id=case_id,
        actor=f"user-{current_role.lower()}",
        role=current_role,
        tenant_id=tenant_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return {"status": "success", "message": f"Case {case_id} soft deleted"}


@router.get("/{case_id}/network")
def get_case_network(
    case_id: str = FastAPIPath(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$", description="Valid alphanumeric Case ID"),
    hops: int = Query(2, ge=1, le=4, description="Graph traversal hop radius"),
    tenant_id: str = Query("default", description="Tenant ID"),
):
    """Retrieve entity relationship subgraph and shared mule linkages for a case."""
    entity = repository.get_case(case_id=case_id, tenant_id=tenant_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    graph_svc = get_graph_service()
    subgraph = graph_svc.get_subgraph_for_case(case_id=case_id, hops=hops)
    mule_rings = graph_svc.detect_mule_rings(min_cases=2)
    # Filter mule rings relevant to this case
    relevant_rings = [r for r in mule_rings if case_id.upper() in [c.upper() for c in r.get("linked_cases", [])]]

    return {
        "case_id": case_id,
        "graph": subgraph,
        "mule_ring_alerts": relevant_rings,
    }


@router.post("/{case_id}/sar", dependencies=[Depends(require_role(UserRole.COMPLIANCE_OFFICER, UserRole.ADMIN))])
def generate_case_sar(
    case_id: str = FastAPIPath(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$", description="Valid alphanumeric Case ID"),
    format: str = Query("xml", pattern=r"^(xml|json)$", description="Export format: xml or json"),
    tenant_id: str = Query("default", description="Tenant ID"),
    current_role: str = Depends(get_current_role),
):
    """Generate regulatory Suspicious Activity Report (FinCEN XML or JSON audit dossier)."""
    entity = repository.get_case(case_id=case_id, tenant_id=tenant_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    case_dict = entity.to_dict()
    safe_filename_id = re.sub(r"[^A-Za-z0-9_\-]", "", case_id).upper()

    if format == "json":
        dossier = generate_sar_dossier(case_dict, investigator_id=f"COMPLIANCE-{current_role}")
        return dossier

    xml_content = generate_sar_xml(case_dict)
    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="SAR_FinCEN_{safe_filename_id}.xml"'
        },
    )


@router.get("/{case_id}/export")
def export_case_report(
    case_id: str = FastAPIPath(..., pattern=r"^[A-Za-z0-9_\-]{1,64}$", description="Valid alphanumeric Case ID"),
    tenant_id: str = Query("default", description="Tenant ID"),
):
    """Export forensic report for a case as downloadable JSON for compliance & filing."""
    entity = repository.get_case(case_id=case_id, tenant_id=tenant_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

    c = entity.to_dict()
    export_data = {
        "report_type": "FORENSIC_FRAUD_INCIDENT_DOSSIER",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_metadata": {
            "case_id": c.get("case_id"),
            "transaction_id": c.get("transaction_id"),
            "status": c.get("status"),
            "risk_score": c.get("risk_score"),
            "assigned_to": c.get("assigned_to"),
            "created_at": c.get("created_at"),
        },
        "entity_details": {
            "account_holder": c.get("account_holder"),
            "account_number": c.get("account_number"),
            "upi_id": c.get("upi_id"),
            "card_last4": c.get("card_last4"),
            "phone": c.get("phone"),
            "email": c.get("email"),
            "address": c.get("address"),
            "linked_accounts": c.get("linked_accounts", []),
        },
        "financial_telemetry": {
            "amount": c.get("amount"),
            "timestamp": c.get("timestamp"),
        },
        "investigation_trail": {
            "complaint_text": c.get("complaint_text"),
            "investigator_notes": c.get("investigator_notes"),
        },
    }
    content = json.dumps(export_data, indent=2)
    safe_filename_id = re.sub(r"[^A-Za-z0-9_\-]", "", case_id).upper()
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="case_{safe_filename_id}_report.json"'
        },
    )
