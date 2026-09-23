"""Suspicious Activity Report (SAR) compiler producing FinCEN-compliant XML and structured forensic dossiers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from app.security.pii_masker import mask_pii


def _sanitize_xml(val: Any) -> str:
    """Safely escape text for inclusion in FinCEN XML document."""
    if val is None:
        return ""
    return xml_escape(str(val))


def generate_sar_narrative(case: dict[str, Any]) -> str:
    """Generate regulatory narrative synthesizing timeline, financial exposure, and investigation notes."""
    case_id = case.get("case_id", "UNKNOWN")
    holder = case.get("account_holder", "Unidentified Individual")
    acc = case.get("account_number", "UNKNOWN")
    amount = case.get("amount", 0.0)
    risk_score = case.get("risk_score", 0.0)
    complaint = case.get("complaint_text", "No customer complaint on record.")
    notes = case.get("investigator_notes", "Standard algorithmic trigger.")
    linked = case.get("linked_accounts", [])
    upi = case.get("upi_id", "N/A")

    narrative = (
        f"PART V - SUSPICIOUS ACTIVITY NARRATIVE SUMMARY\n"
        f"Case Reference: {case_id} | Risk Rating: {risk_score:.4f}\n\n"
        f"1. SUBJECT AND TRANSACTION BACKGROUND:\n"
        f"On or around {case.get('timestamp', 'recent reporting period')}, internal automated transaction monitoring "
        f"flagged suspicious high-velocity financial activity associated with account {acc} belonging to {holder}. "
        f"The primary flagged transaction involved an unauthorized or anomalous transfer of {amount:,.2f} "
        f"routed through UPI handle '{upi}'.\n\n"
        f"2. FORENSIC FINDINGS AND ANOMALIES:\n"
        f"Initial report details: {complaint}\n"
        f"Investigator Forensic Trail: {notes}\n\n"
        f"3. NETWORK & MONEY MULE CORRELATION:\n"
    )

    if linked:
        narrative += (
            f"Cross-entity graph traversal identified {len(linked)} correlated transfer endpoints: "
            f"{', '.join(str(a) for a in linked)}. Multi-hop routing patterns suggest structured layering "
            f"indicative of coordinated money mule syndicates.\n\n"
        )
    else:
        narrative += "No secondary external accounts detected in immediate 1-hop topology.\n\n"

    narrative += (
        f"4. DISPOSITION AND REGULATORY ACTION:\n"
        f"Due to the severity of risk indicators (Composite Score: {risk_score:.2%}), account activity was halted, "
        f"and this Suspicious Activity Report is submitted pursuant to 31 CFR § 1020.320 / FinCEN guidelines."
    )
    return narrative


def generate_sar_xml(
    case: dict[str, Any],
    filing_institution: str = "Enterprise FinTech Fraud Defense Bank N.A.",
    fincen_identifier: str = "FINCEN-BSA-XML-2.0",
) -> str:
    """Compile standardized FinCEN/FIU XML regulatory filing report."""
    activity_id = f"SAR-{case.get('case_id', uuid.uuid4().hex[:8]).upper()}"
    timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    narrative_text = generate_sar_narrative(case)

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<SuspiciousActivityReport xmlns="http://www.fincen.gov/bsa/sar" schemaVersion="{fincen_identifier}">',
        '  <ActivitySeqNum>' + _sanitize_xml(activity_id) + '</ActivitySeqNum>',
        '  <FilingDate>' + timestamp_utc + '</FilingDate>',
        '  <FilingInstitutionDetail>',
        '    <LegalName>' + _sanitize_xml(filing_institution) + '</LegalName>',
        '    <FilingType>INITIAL_REPORT</FilingType>',
        '    <Jurisdiction>US-FINCEN</Jurisdiction>',
        '  </FilingInstitutionDetail>',
        '  <ActivityDetail>',
        '    <CaseID>' + _sanitize_xml(case.get("case_id")) + '</CaseID>',
        '    <TransactionID>' + _sanitize_xml(case.get("transaction_id")) + '</TransactionID>',
        '    <SuspiciousAmount currency="USD">' + f"{float(case.get('amount', 0.0)):.2f}" + '</SuspiciousAmount>',
        '    <RiskScore>' + f"{float(case.get('risk_score', 0.0)):.4f}" + '</RiskScore>',
        '    <IncidentDate>' + _sanitize_xml(case.get("timestamp")) + '</IncidentDate>',
        '    <SuspiciousCategory>FRAUD_WIRE_UPI_MULE</SuspiciousCategory>',
        '  </ActivityDetail>',
        '  <SubjectInformation>',
        '    <PrimaryAccountHolder>' + _sanitize_xml(case.get("account_holder")) + '</PrimaryAccountHolder>',
        '    <AccountNumber>' + _sanitize_xml(case.get("account_number")) + '</AccountNumber>',
        '    <CardLast4>' + _sanitize_xml(case.get("card_last4")) + '</CardLast4>',
        '    <UPIIdentifier>' + _sanitize_xml(case.get("upi_id")) + '</UPIIdentifier>',
        '    <ContactPhone>' + _sanitize_xml(case.get("phone")) + '</ContactPhone>',
        '    <ContactEmail>' + _sanitize_xml(case.get("email")) + '</ContactEmail>',
        '    <PhysicalAddress>' + _sanitize_xml(case.get("address")) + '</PhysicalAddress>',
        '  </SubjectInformation>',
        '  <SuspiciousActivityInformation>',
        '    <MuleRingIndicators>',
    ]

    for linked in case.get("linked_accounts", []):
        xml_lines.append(f'      <CorrelatedDestinationAccount>{_sanitize_xml(linked)}</CorrelatedDestinationAccount>')

    xml_lines.extend([
        '    </MuleRingIndicators>',
        '  </SuspiciousActivityInformation>',
        '  <NarrativeSummary>',
        '    <NarrativeText><![CDATA[' + narrative_text + ']]></NarrativeText>',
        '  </NarrativeSummary>',
        '</SuspiciousActivityReport>',
    ])

    return "\n".join(xml_lines)


def generate_sar_dossier(
    case: dict[str, Any],
    investigator_id: str = "COMPLIANCE-OFFICER-01",
    redact_pii: bool = False,
) -> dict[str, Any]:
    """Generate complete forensic compliance dossier in structured JSON format."""
    narrative = generate_sar_narrative(case)
    if redact_pii:
        narrative = mask_pii(narrative)

    dossier_id = f"DOSSIER-{case.get('case_id', uuid.uuid4().hex[:8]).upper()}"

    timeline = [
        {
            "event": "INCIDENT_TIMESTAMP",
            "time": case.get("timestamp"),
            "details": f"Transaction initiated for amount {case.get('amount')}",
        },
        {
            "event": "CASE_OPENED",
            "time": case.get("created_at"),
            "details": f"Algorithmic alert triggered with score {case.get('risk_score')}",
        },
        {
            "event": "SAR_FILING_COMPILED",
            "time": datetime.now(timezone.utc).isoformat(),
            "details": f"Regulatory compliance dossier prepared by {investigator_id}",
        },
    ]

    return {
        "dossier_id": dossier_id,
        "filing_standard": "FINCEN_FORM_111_BSAR_V2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "investigator_id": investigator_id,
        "case_metadata": {
            "case_id": case.get("case_id"),
            "status": case.get("status"),
            "assigned_to": case.get("assigned_to"),
            "risk_score": case.get("risk_score"),
        },
        "subject_profile": {
            "account_holder": case.get("account_holder"),
            "account_number": case.get("account_number"),
            "upi_id": case.get("upi_id"),
            "phone": case.get("phone"),
            "email": case.get("email"),
            "address": case.get("address"),
        },
        "financial_exposure": {
            "primary_transaction_id": case.get("transaction_id"),
            "amount": case.get("amount"),
            "currency": "USD",
            "linked_mule_accounts": case.get("linked_accounts", []),
        },
        "investigation_timeline": timeline,
        "forensic_narrative": narrative,
        "regulatory_certification": {
            "bsa_officer_affirmed": True,
            "fincen_submission_ready": True,
            "statutory_retention_years": 5,
        },
    }
