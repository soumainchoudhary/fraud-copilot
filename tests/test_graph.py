"""Tests for entity relationship graph builder, subgraphs, and mule ring detection."""
import pytest

from app.graph.graph_service import EntityGraphService


@pytest.fixture
def sample_network_cases():
    return [
        {
            "case_id": "CASE-101",
            "account_number": "ACC-MULE-HUB",
            "upi_id": "mulehub@okaxis",
            "amount": 80000.0,
            "risk_score": 0.95,
            "status": "escalated",
            "linked_accounts": ["ACC-TARGET-A", "ACC-TARGET-B"],
            "device_ids": ["DEV-SHARED-01"],
            "ip_addresses": ["198.51.100.22"],
            "phone": "+919999999991",
        },
        {
            "case_id": "CASE-102",
            "account_number": "ACC-MULE-HUB",
            "upi_id": "mulehub@okaxis",
            "amount": 95000.0,
            "risk_score": 0.98,
            "status": "escalated",
            "linked_accounts": ["ACC-TARGET-C"],
            "device_ids": ["DEV-SHARED-01"],
            "ip_addresses": ["198.51.100.22"],
            "phone": "+919999999991",
        },
        {
            "case_id": "CASE-103",
            "account_number": "ACC-ISOLATED",
            "upi_id": "clean@okhdfc",
            "amount": 1500.0,
            "risk_score": 0.12,
            "status": "open",
            "linked_accounts": [],
            "device_ids": ["DEV-CLEAN-99"],
            "ip_addresses": ["203.0.113.5"],
            "phone": "+919999999992",
        },
    ]


class TestEntityGraphService:

    def test_build_graph_nodes_and_edges(self, sample_network_cases):
        service = EntityGraphService()
        g = service.build_graph(sample_network_cases)

        # Graph must contain case nodes and entity nodes
        assert g.has_node("case:CASE-101")
        assert g.has_node("case:CASE-102")
        assert g.has_node("acc:ACC-MULE-HUB")
        assert g.has_node("upi:mulehub@okaxis")
        assert g.has_node("dev:DEV-SHARED-01")

        # Edge from case to account
        assert g.has_edge("case:CASE-101", "acc:ACC-MULE-HUB")
        assert g.has_edge("case:CASE-102", "acc:ACC-MULE-HUB")

    def test_get_subgraph_for_case(self, sample_network_cases):
        service = EntityGraphService()
        service.build_graph(sample_network_cases)

        subgraph_data = service.get_subgraph_for_case("CASE-101", hops=2)
        assert subgraph_data["case_id"] == "CASE-101"
        assert len(subgraph_data["nodes"]) >= 4
        assert len(subgraph_data["edges"]) >= 3

        # Must mark target node
        target_nodes = [n for n in subgraph_data["nodes"] if n["is_target"]]
        assert len(target_nodes) == 1
        assert target_nodes[0]["id"] == "case:CASE-101"

    def test_detect_mule_rings(self, sample_network_cases):
        service = EntityGraphService()
        service.build_graph(sample_network_cases)

        rings = service.detect_mule_rings(min_cases=2)
        assert len(rings) >= 1

        # The hub should be ACC-MULE-HUB or DEV-SHARED-01 connecting CASE-101 and CASE-102
        ring_hubs = [r["hub_entity"] for r in rings]
        assert "acc:ACC-MULE-HUB" in ring_hubs or "dev:DEV-SHARED-01" in ring_hubs

        matched_ring = rings[0]
        assert "CASE-101" in matched_ring["linked_cases"]
        assert "CASE-102" in matched_ring["linked_cases"]
        assert matched_ring["case_count"] == 2
        assert matched_ring["total_exposure_amount"] >= 175000.0
        assert matched_ring["ring_classification"] == "CRITICAL_MULE_HUB"
