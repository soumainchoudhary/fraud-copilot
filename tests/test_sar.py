"""Tests for FinCEN SAR XML regulatory report and JSON forensic dossier generation."""
import xml.etree.ElementTree as ET

import pytest

from app.compliance.sar_generator import (
    generate_sar_dossier,
    generate_sar_xml,
)


@pytest.fixture
def mock_case_dict():
    return {
        "case_id": "CASE-SAR-001",
        "transaction_id": "TXN-SAR-999",
        "account_holder": "Alice Walker",
        "account_number": "123456789012",
        "upi_id": "alicew@okaxis",
        "card_last4": "1122",
        "phone": "+919876543210",
        "email": "alice.walker@example.com",
        "address": "42 Market Street, Financial District",
        "risk_score": 0.985,
        "amount": 125000.50,
        "timestamp": "2026-09-20T14:30:00",
        "complaint_text": "Victim reported social engineering scam and unauthorized fund transfer.",
        "investigator_notes": "Correlated with mule syndicate operating in Mumbai. Multiple rapid outbound hops.",
        "linked_accounts": ["987654321098", "456789012345"],
        "assigned_to": "INV-LEAD-07",
        "created_at": "2026-09-20T15:00:00",
        "status": "escalated",
    }


class TestSARGenerator:

    def test_sar_xml_structure_and_well_formedness(self, mock_case_dict):
        xml_string = generate_sar_xml(mock_case_dict)
        assert xml_string.startswith('<?xml version="1.0" encoding="UTF-8"?>')

        # Parse XML tree to verify structural validity
        root = ET.fromstring(xml_string)
        assert root.tag.endswith("SuspiciousActivityReport")

        # Verify key child blocks exist
        activity_seq = root.find("{http://www.fincen.gov/bsa/sar}ActivitySeqNum")
        assert activity_seq is not None
        assert "CASE-SAR-001" in activity_seq.text

        # Verify Subject Information
        subj = root.find("{http://www.fincen.gov/bsa/sar}SubjectInformation")
        assert subj is not None
        holder = subj.find("{http://www.fincen.gov/bsa/sar}PrimaryAccountHolder")
        assert holder.text == "Alice Walker"

        # Verify Suspicious Amount
        act_detail = root.find("{http://www.fincen.gov/bsa/sar}ActivityDetail")
        amount_el = act_detail.find("{http://www.fincen.gov/bsa/sar}SuspiciousAmount")
        assert amount_el.text == "125000.50"

        # Verify Narrative
        narrative = root.find("{http://www.fincen.gov/bsa/sar}NarrativeSummary")
        assert narrative is not None
        narr_text = narrative.find("{http://www.fincen.gov/bsa/sar}NarrativeText")
        assert "PART V - SUSPICIOUS ACTIVITY NARRATIVE SUMMARY" in narr_text.text

    def test_sar_xml_escaping(self, mock_case_dict):
        # Insert characters that would break unescaped XML
        mock_case_dict["account_holder"] = "Alice & Bob <Partners> \"LLC\""
        xml_string = generate_sar_xml(mock_case_dict)
        # Must be valid XML
        root = ET.fromstring(xml_string)
        holder = root.find(".//{http://www.fincen.gov/bsa/sar}PrimaryAccountHolder")
        assert holder.text == "Alice & Bob <Partners> \"LLC\""

    def test_sar_json_dossier_structure(self, mock_case_dict):
        dossier = generate_sar_dossier(mock_case_dict, investigator_id="COMPLIANCE-OFFICER-42")
        assert dossier["filing_standard"] == "FINCEN_FORM_111_BSAR_V2"
        assert dossier["dossier_id"].startswith("DOSSIER-CASE-SAR-001")
        assert dossier["subject_profile"]["account_holder"] == "Alice Walker"
        assert dossier["financial_exposure"]["amount"] == 125000.50
        assert len(dossier["financial_exposure"]["linked_mule_accounts"]) == 2
        assert len(dossier["investigation_timeline"]) >= 3
        assert dossier["regulatory_certification"]["bsa_officer_affirmed"] is True
