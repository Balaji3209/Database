"""Module 3 - Dependency intelligence (NetworkX)."""
from __future__ import annotations

import networkx as nx
import pandas as pd

from .config import get_logger

log = get_logger("dependency_intel")


def build_graph(deps: pd.DataFrame, instances: pd.DataFrame, apps: pd.DataFrame) -> nx.DiGraph:
    """Directed graph: edge source -> target means 'source depends on target'."""
    g = nx.DiGraph()
    for a in apps.itertuples():
        g.add_node(a.application_id, kind="application", label=a.application_name, service=a.business_service,
                   tier=a.criticality_tier)
    for i in instances.itertuples():
        g.add_node(i.instance_id, kind="database", label=f"{i.instance_id} ({i.db_engine})", engine=i.db_engine,
                   environment=i.environment, service=i.business_service, evidence=i.dependency_evidence)
    for d in deps.itertuples():
        if d.source_id not in g:
            g.add_node(d.source_id, kind="application", label=d.source_id, service="", tier="Unknown")
        g.add_edge(d.source_id, d.target_id, dtype=d.dependency_type, interface=d.interface, criticality=d.criticality,
                   status=d.status, evidence=d.evidence_source, confidence=d.confidence)
    log.info("Dependency graph: %d nodes, %d edges", g.number_of_nodes(), g.number_of_edges())
    return g


def profiles(g: nx.DiGraph, instances: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for i in instances.itertuples():
        n = i.instance_id
        active_in = [p for p in g.predecessors(n) if g.edges[p, n]["status"] == "Active"]
        db_dependants = [p for p in active_in if g.nodes[p].get("kind") == "database"]
        upstream = list(g.successors(n))
        critical = any(g.edges[p, n]["criticality"] == "Critical" for p in active_in)
        known = i.dependency_evidence != "None"
        quality = {"APM + DB catalogue": "High", "CMDB relationship only": "Low", "None": "Missing"}.get(i.dependency_evidence, "Low")
        rows.append(dict(instance_id=n, dependencies_known=known, dependency_evidence_quality=quality,
                         active_dependants=len(active_in), db_dependants=len(db_dependants), upstream_dependencies=len(upstream),
                         dormant_links=sum(1 for p in g.predecessors(n) if g.edges[p, n]["status"] == "Dormant"),
                         critical_dependency=critical, dependants=", ".join(active_in), depends_on=", ".join(upstream)))
    return pd.DataFrame(rows)


def move_groups(g: nx.DiGraph) -> dict[str, str]:
    """Databases linked by db-to-db interfaces must be planned in the same migration wave."""
    db_edges = [(u, v) for u, v, d in g.edges(data=True)
                if g.nodes[u].get("kind") == "database" and g.nodes[v].get("kind") == "database"]
    sub = nx.Graph()
    sub.add_edges_from(db_edges)
    groups = {}
    for k, comp in enumerate(sorted(nx.connected_components(sub), key=len, reverse=True), start=1):
        for n in comp:
            groups[n] = f"MG-{k:02d}"
    return groups


def critical_nodes(g: nx.DiGraph, top: int = 10) -> pd.DataFrame:
    centrality = nx.degree_centrality(g)
    rows = [dict(node=n, kind=g.nodes[n].get("kind"), label=g.nodes[n].get("label", n), degree=g.degree(n),
                 centrality=round(c, 3)) for n, c in centrality.items()]
    return pd.DataFrame(rows).sort_values(["degree", "centrality"], ascending=False).head(top)
