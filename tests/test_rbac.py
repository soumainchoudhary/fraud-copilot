"""Tests for Role-Based Access Control (RBAC) and privileged endpoint security."""
from fastapi.testclient import TestClient


class TestEnterpriseRBAC:

    def test_invalid_role_header_rejected_403(self, client: TestClient):
        response = client.get("/cases", headers={"X-User-Role": "SUPER_HACKER"})
        assert response.status_code == 403
        assert "Invalid security role" in response.json()["detail"]

    def test_analyst_l1_cannot_generate_sar_403(self, client: TestClient):
        # First retrieve a valid case ID
        list_res = client.get("/cases")
        cases = list_res.json()["items"]
        assert len(cases) > 0
        case_id = cases[0]["case_id"]

        # Call SAR with L1 Analyst role -> Must be 403 Forbidden
        sar_res = client.post(
            f"/cases/{case_id}/sar",
            headers={"X-User-Role": "ANALYST_L1"},
        )
        assert sar_res.status_code == 403
        assert "Insufficient privileges" in sar_res.json()["detail"]

    def test_investigator_l2_cannot_generate_sar_403(self, client: TestClient):
        list_res = client.get("/cases")
        case_id = list_res.json()["items"][0]["case_id"]

        # L2 Investigator is not authorized for regulatory FinCEN SAR generation
        sar_res = client.post(
            f"/cases/{case_id}/sar",
            headers={"X-User-Role": "INVESTIGATOR_L2"},
        )
        assert sar_res.status_code == 403

    def test_compliance_officer_can_generate_sar(self, client: TestClient):
        list_res = client.get("/cases")
        case_id = list_res.json()["items"][0]["case_id"]

        # Compliance officer can generate XML SAR
        sar_res = client.post(
            f"/cases/{case_id}/sar?format=xml",
            headers={"X-User-Role": "COMPLIANCE_OFFICER"},
        )
        assert sar_res.status_code == 200
        assert "application/xml" in sar_res.headers["content-type"]
        assert "SuspiciousActivityReport" in sar_res.text

        # Compliance officer can also generate JSON dossier
        sar_json_res = client.post(
            f"/cases/{case_id}/sar?format=json",
            headers={"X-User-Role": "COMPLIANCE_OFFICER"},
        )
        assert sar_json_res.status_code == 200
        dossier = sar_json_res.json()
        assert dossier["filing_standard"] == "FINCEN_FORM_111_BSAR_V2"

    def test_non_admin_cannot_delete_case_403(self, client: TestClient):
        list_res = client.get("/cases")
        case_id = list_res.json()["items"][0]["case_id"]

        del_res = client.delete(
            f"/cases/{case_id}",
            headers={"X-User-Role": "INVESTIGATOR_L2"},
        )
        assert del_res.status_code == 403

    def test_admin_can_delete_case(self, client: TestClient):
        list_res = client.get("/cases")
        case_id = list_res.json()["items"][0]["case_id"]

        del_res = client.delete(
            f"/cases/{case_id}",
            headers={"X-User-Role": "ADMIN"},
        )
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "success"
