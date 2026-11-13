"""Orchestrates all intelligence services into one explainable estate analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import database, dependency_intel, license_intel, reconciliation, risk_intel, tco
from .config import DATA_DIR, get_logger
from .data_generator import generate
from .decision_engine import DecisionEngine

log = get_logger("pipeline")

FILES = ["database_instances", "applications", "workload_metrics", "feature_usage", "recovery_requirements",
         "dependencies", "cost_records", "license_entitlements", "cmdb_extract", "discovery_scan",
         "validation_sample", "expected_outcomes"]


@dataclass(frozen=True)
class Scenario:
    """Jury what-if scenarios."""
    oracle_discovery_unavailable: bool = False
    budget_cut_pct: float = 0.0
    ai_privacy_strict: bool = False


@dataclass
class Analysis:
    scenario: Scenario
    data: dict
    recon: dict
    licence_position: pd.DataFrame
    findings: pd.DataFrame
    graph: object
    dep_profiles: pd.DataFrame
    move_groups: dict
    risk: pd.DataFrame
    recs: pd.DataFrame
    options: pd.DataFrame
    evidence: pd.DataFrame
    tco: dict
    tco_curve: pd.DataFrame
    levers: pd.DataFrame
    licence_opt: dict
    budget: dict
    waves: pd.DataFrame
    kpis: dict = field(default_factory=dict)

    @property
    def estate(self) -> pd.DataFrame:
        """Single wide view: inventory + workload + risk + recommendation."""
        d = self.data
        return (d["database_instances"]
                .merge(d["workload_metrics"][["instance_id", "cpu_p95_pct", "memory_used_pct", "connections_90d",
                                              "last_connection_date"]], on="instance_id")
                .merge(d["recovery_requirements"][["instance_id", "criticality_tier", "rpo_minutes", "rto_minutes"]], on="instance_id")
                .merge(self.risk, on="instance_id")
                .merge(self.recs[["instance_id", "recommended_action", "target_platform", "readiness", "confidence",
                                  "annual_saving", "one_time_cost", "human_decision"]], on="instance_id"))


def load_data(data_dir: Path = DATA_DIR) -> dict[str, pd.DataFrame]:
    if not all((data_dir / f"{f}.csv").exists() for f in FILES):
        log.info("Synthetic data not found - generating")
        generate(data_dir)
    data = {}
    for f in FILES:
        df = pd.read_csv(data_dir / f"{f}.csv", keep_default_na=False, na_values=[""])
        data[f] = df
    inst = data["database_instances"]
    for col in ("owner", "application_id", "business_service", "cmdb_ci_id", "discovery_source_ref", "collected_at"):
        inst[col] = inst[col].fillna("").astype(str)
    for col in ("uses_java_or_aq", "uses_clr", "uses_filestream", "uses_cross_db_queries", "uses_sql_agent_jobs",
                "uses_ssis", "esu_or_sustaining_support"):
        inst[col] = inst[col].astype(str).str.lower().eq("true")
    data["feature_usage"]["currently_used"] = data["feature_usage"]["currently_used"].astype(str).str.lower().eq("true")
    for k in ("cmdb_extract", "discovery_scan", "workload_metrics"):
        data[k] = data[k].fillna("")
    return data


def run(scenario: Scenario = Scenario(), data_dir: Path = DATA_DIR, persist: bool = True) -> Analysis:
    data = load_data(data_dir)
    oracle_ok = not scenario.oracle_discovery_unavailable
    recon = reconciliation.reconcile(data["cmdb_extract"], data["discovery_scan"], data["database_instances"],
                                     {"Oracle": oracle_ok, "SQL Server": True})
    lic_pos = license_intel.licence_position(data["license_entitlements"], data["database_instances"], data["feature_usage"])
    findings = license_intel.instance_findings(data["database_instances"], data["feature_usage"], oracle_ok)
    graph = dependency_intel.build_graph(data["dependencies"], data["database_instances"], data["applications"])
    profiles = dependency_intel.profiles(graph, data["database_instances"])
    groups = dependency_intel.move_groups(graph)
    risk = risk_intel.assess(data["database_instances"], data["recovery_requirements"], findings, profiles)
    engine = DecisionEngine(data, risk, profiles, oracle_discovery_available=oracle_ok)
    recs, options, evidence = engine.run()

    decisions = database.latest_decisions() if persist else pd.DataFrame()
    if not decisions.empty:
        recs = recs.merge(decisions[["recommendation_id", "decision"]], on="recommendation_id", how="left")
        recs["human_decision"] = recs.pop("decision").fillna("Pending")

    lic_opt = tco.licence_optimisation(recs, lic_pos, data["cost_records"])
    analysis = Analysis(
        scenario=scenario, data=data, recon=recon, licence_position=lic_pos, findings=findings, graph=graph,
        dep_profiles=profiles, move_groups=groups, risk=risk, recs=recs, options=options, evidence=evidence,
        tco=tco.tco_summary(recs), tco_curve=tco.portfolio_tco(recs), levers=tco.savings_by_lever(recs, lic_pos),
        licence_opt=lic_opt, budget=tco.budget_scenario(recs, risk, scenario.budget_cut_pct or 20.0),
        waves=tco.migration_waves(recs, risk, groups))
    analysis.kpis = success_measures(analysis)
    if persist:
        try:
            database.load_evidence(data)
            database.save_recommendations(recs, evidence)
        except Exception as exc:  # persistence must never break the advisory view
            log.error("Persisting results failed: %s", exc)
    return analysis


def success_measures(a: Analysis) -> dict:
    v = a.data["validation_sample"]
    v_match = v["match"].astype(str).str.lower().eq("true")
    eligible = a.recs[a.recs.recommended_action != "Retain"]
    ready_strict = (eligible.readiness == "Ready").sum()
    ready_cond = eligible.readiness.isin(["Ready", "Conditional"]).sum()
    ev_counts = a.evidence.groupby("recommendation_id").size()
    traced = a.recs.apply(lambda r: ev_counts.get(r.recommendation_id, 0) > 0 and bool(r.assumptions)
                          and pd.notna(r.confidence_pct) and bool(r.human_decision) and pd.notna(r.annual_saving), axis=1)
    return {
        "reconciliation": dict(name="Inventory reconciliation", target=">= 95%", actual=a.recon["summary"]["reconciliation_rate"],
                               met=a.recon["summary"]["reconciliation_rate"] >= 95,
                               detail=f"{a.recon['summary']['fully_reconciled']}/{a.recon['summary']['pilot_instances']} instances "
                                      "resolved to owner, application, version, edition & lifecycle"
                                      + (f" ({a.recon['summary']['stale_snapshot']} from last-known snapshot)"
                                         if a.recon["summary"].get("stale_snapshot") else "")),
        "mapping_accuracy": dict(name="Edition / feature / dependency mapping accuracy (SME-validated)", target=">= 90%",
                                 actual=round(100 * v_match.mean(), 1), met=v_match.mean() >= 0.9,
                                 detail=f"{int(v_match.sum())}/{len(v)} sampled mappings confirmed by SMEs"),
        "licence_optimisation": dict(name="Addressable licence / support optimisation", target="10-15% proposed",
                                     actual=a.licence_opt["proposed_pct"], met=a.licence_opt["proposed_pct"] >= 10,
                                     detail=f"£{a.licence_opt['proposed']:,.0f} proposed of £{a.licence_opt['licence_support_spend']:,.0f} "
                                            f"annual licence & support spend (+£{a.licence_opt['potential']:,.0f} potential, evidence pending)"),
        "migration_ready": dict(name="Migration-ready recommendations for eligible candidates", target=">= 80%",
                                actual=round(100 * ready_cond / len(eligible), 1) if len(eligible) else 0,
                                met=(ready_cond / len(eligible) >= 0.8) if len(eligible) else False,
                                detail=f"{ready_cond}/{len(eligible)} eligible candidates not blocked "
                                       f"({ready_strict} fully Ready, {ready_cond - ready_strict} Ready-with-conditions)"),
        "traceability": dict(name="Recommendations traced to evidence, assumptions, confidence, decision & value",
                             target="100%", actual=round(100 * traced.mean(), 1), met=traced.all(),
                             detail=f"{int(traced.sum())}/{len(a.recs)} recommendations fully traceable"),
    }
