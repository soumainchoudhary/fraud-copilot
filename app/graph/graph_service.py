"""Graph intelligence service for entity resolution and money mule ring detection using NetworkX."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
import structlog

logger = structlog.get_logger(__name__)


class EntityGraphService:
    """Multi-entity relationship graph linking cases, bank accounts, UPIs, devices, and IPs."""

    def __init__(self):
        self.graph = nx.Graph()
        self._case_index: dict[str, str] = {}  # case_id -> node_id

    def build_graph(self, cases: list[dict[str, Any]]) -> nx.Graph:
        """Construct graph topology from a list of fraud case dictionaries."""
        g = nx.Graph()

        for c in cases:
            case_id = c.get("case_id")
            if not case_id:
                continue

            case_node = f"case:{case_id}"
            risk_score = float(c.get("risk_score", 0.0))
            g.add_node(
                case_node,
                id=case_node,
                label=case_id,
                entity_type="case",
                risk_score=risk_score,
                status=c.get("status", "open"),
                amount=float(c.get("amount", 0.0)),
            )

            # 1. Primary Account
            acc = c.get("account_number")
            if acc:
                acc_node = f"acc:{acc}"
                if not g.has_node(acc_node):
                    g.add_node(
                        acc_node,
                        id=acc_node,
                        label=acc,
                        entity_type="account",
                        holder=c.get("account_holder", "Unknown"),
                        risk_score=risk_score,
                    )
                else:
                    g.nodes[acc_node]["risk_score"] = max(g.nodes[acc_node].get("risk_score", 0.0), risk_score)
                g.add_edge(case_node, acc_node, relation="INVOLVES_ACCOUNT")

            # 2. UPI Identifier
            upi = c.get("upi_id")
            if upi:
                upi_node = f"upi:{upi}"
                if not g.has_node(upi_node):
                    g.add_node(upi_node, id=upi_node, label=upi, entity_type="upi", risk_score=risk_score)
                else:
                    g.nodes[upi_node]["risk_score"] = max(g.nodes[upi_node].get("risk_score", 0.0), risk_score)
                g.add_edge(case_node, upi_node, relation="ROUTED_VIA_UPI")
                if acc:
                    g.add_edge(f"acc:{acc}", upi_node, relation="LINKED_UPI")

            # 3. Linked Accounts (Mule network bridges)
            for linked in c.get("linked_accounts", []):
                if linked and linked != acc:
                    linked_node = f"acc:{linked}"
                    if not g.has_node(linked_node):
                        g.add_node(linked_node, id=linked_node, label=linked, entity_type="account", risk_score=risk_score * 0.9)
                    g.add_edge(case_node, linked_node, relation="MULE_HOP")
                    if acc:
                        g.add_edge(f"acc:{acc}", linked_node, relation="TRANSFERRED_TO")

            # 4. Device IDs
            for dev in c.get("device_ids", []):
                if dev:
                    dev_node = f"dev:{dev}"
                    if not g.has_node(dev_node):
                        g.add_node(dev_node, id=dev_node, label=dev, entity_type="device", risk_score=risk_score)
                    g.add_edge(case_node, dev_node, relation="ACCESSED_FROM_DEVICE")

            # 5. IP Addresses
            for ip in c.get("ip_addresses", []):
                if ip:
                    ip_node = f"ip:{ip}"
                    if not g.has_node(ip_node):
                        g.add_node(ip_node, id=ip_node, label=ip, entity_type="ip", risk_score=risk_score)
                    g.add_edge(case_node, ip_node, relation="ORIGINATED_FROM_IP")

            # 6. Phone Numbers
            phone = c.get("phone")
            if phone:
                phone_node = f"phone:{phone}"
                if not g.has_node(phone_node):
                    g.add_node(phone_node, id=phone_node, label=phone, entity_type="phone", risk_score=risk_score)
                g.add_edge(case_node, phone_node, relation="REGISTERED_PHONE")

        self.graph = g
        logger.info("entity_graph_built", nodes=g.number_of_nodes(), edges=g.number_of_edges())
        return self.graph

    def get_subgraph_for_case(self, case_id: str, hops: int = 2) -> dict[str, Any]:
        """Extract ego-network subgraph around a case up to specified hop distance."""
        case_node = f"case:{case_id.upper()}"
        if not self.graph.has_node(case_node):
            # Try finding without case: prefix or case-insensitive
            matched = [n for n in self.graph.nodes if n.lower() == case_node.lower() or n.lower() == f"case:{case_id.lower()}"]
            if matched:
                case_node = matched[0]
            else:
                return {
                    "case_id": case_id,
                    "nodes": [],
                    "edges": [],
                    "metrics": {"total_nodes": 0, "total_edges": 0, "shared_entities": 0},
                }

        # Ego graph with radius `hops`
        sub_g = nx.ego_graph(self.graph, case_node, radius=hops)

        nodes = []
        for n, attrs in sub_g.nodes(data=True):
            nodes.append({
                "id": n,
                "label": attrs.get("label", n),
                "type": attrs.get("entity_type", "entity"),
                "risk_score": attrs.get("risk_score", 0.0),
                "degree": sub_g.degree(n),
                "is_target": n == case_node,
            })

        edges = []
        for u, v, attrs in sub_g.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "relation": attrs.get("relation", "LINKED"),
            })

        # Calculate high-risk shared hubs (nodes with degree > 2 connecting multiple cases)
        shared_hubs = [
            n for n in sub_g.nodes
            if sub_g.degree(n) >= 2 and not n.startswith("case:")
        ]

        metrics = {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "shared_entities": len(shared_hubs),
            "max_degree": max((sub_g.degree(n) for n in sub_g.nodes), default=0),
            "density": round(nx.density(sub_g), 4) if len(nodes) > 1 else 0.0,
        }

        return {
            "case_id": case_id,
            "nodes": nodes,
            "edges": edges,
            "metrics": metrics,
        }

    def detect_mule_rings(self, min_cases: int = 2) -> list[dict[str, Any]]:
        """Identify money mule rings where multiple cases connect to shared accounts, devices, or IPs."""
        rings: list[dict[str, Any]] = []
        if self.graph.number_of_nodes() == 0:
            return rings

        # Check all non-case nodes for multi-case fan-in
        hub_candidates = [
            (node, attrs) for node, attrs in self.graph.nodes(data=True)
            if not str(node).startswith("case:") and self.graph.degree(node) >= min_cases
        ]

        # Sort by degree descending
        hub_candidates.sort(key=lambda x: self.graph.degree(x[0]), reverse=True)

        seen_rings = set()
        for hub_node, hub_attrs in hub_candidates:
            neighbors = list(self.graph.neighbors(hub_node))
            linked_cases = [n for n in neighbors if str(n).startswith("case:")]

            if len(linked_cases) >= min_cases:
                ring_key = tuple(sorted(linked_cases))
                if ring_key in seen_rings:
                    continue
                seen_rings.add(ring_key)

                total_amount = sum(self.graph.nodes[c].get("amount", 0.0) for c in linked_cases)
                avg_risk = sum(self.graph.nodes[c].get("risk_score", 0.0) for c in linked_cases) / len(linked_cases)

                rings.append({
                    "hub_entity": hub_node,
                    "hub_type": hub_attrs.get("entity_type", "unknown"),
                    "hub_label": hub_attrs.get("label", hub_node),
                    "linked_cases": [c.replace("case:", "") for c in linked_cases],
                    "case_count": len(linked_cases),
                    "total_exposure_amount": round(total_amount, 2),
                    "composite_risk_score": round(avg_risk, 4),
                    "ring_classification": "CRITICAL_MULE_HUB" if avg_risk >= 0.8 else "SUSPICIOUS_CLUSTER",
                })

        return rings


# Singleton instance
graph_service = EntityGraphService()


def get_graph_service() -> EntityGraphService:
    """Retrieve singleton entity graph service, auto-populated from case database if empty."""
    global graph_service
    if graph_service.graph.number_of_nodes() == 0:
        cases_file = Path("data/synthetic_cases.json")
        if cases_file.exists():
            try:
                with open(cases_file, "r", encoding="utf-8") as f:
                    cases = json.load(f)
                graph_service.build_graph(cases)
            except Exception as e:
                logger.error("failed_initializing_graph_from_file", error=str(e))
    return graph_service
