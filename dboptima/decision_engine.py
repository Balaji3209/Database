"""Module 5 - Modernization decision engine (rules-first, explainable).

For every database the engine evaluates six options - Retain, Upgrade, Consolidate,
Replatform, Cloud Migrate (Azure) and Retire:

1. HARD CONSTRAINTS are applied first (data residency, technical blockers, unknown
   dependencies / recovery requirements). An option can be:
   - Not feasible : violates a hard constraint - never recommended
   - Blocked      : potentially best, but essential evidence is missing - never "ready"
   - Conditional  : feasible with named conditions requiring human confirmation
   - Feasible     : no known blockers
2. Remaining options are SCORED (0-100) on four transparent criteria:
   value (5-year net benefit), risk reduction, delivery feasibility and strategic fit.
3. Every recommendation carries evidence, assumptions, confidence and a human decision.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from . import reference as ref
from .config import (AZURE_PCI_LANDING_ZONE_APPROVED, CONSOLIDATION_CPU_P95_MAX, CONSOLIDATION_MEM_MAX,
                     PG_REPLATFORM_MAX_PLSQL_OBJECTS, RETIRE_IDLE_DAYS, RIGHTSIZE_TARGET_UTILISATION, ASSESSMENT_DATE,
                     get_logger)
from .data_generator import oracle_processors
from .license_intel import edition_downgrade_saving, edition_fit

log = get_logger("decision_engine")

WEIGHTS = {"value": 0.35, "risk_reduction": 0.30, "feasibility": 0.20, "strategic_fit": 0.15}
LIC_LINES = ("licence_support", "extended_security_updates", "sustaining_support_uplift")
QUALITY = {"High": 1.0, "Medium": 0.7, "Low": 0.4, "Low (stale snapshot)": 0.4, "Missing": 0.0}

ASSUMPTIONS = [
    "Licence and Azure prices are illustrative list-price assumptions (GBP), not negotiated rates.",
    f"Right-sizing targets {int(RIGHTSIZE_TARGET_UTILISATION * 100)}% CPU utilisation at 30-day p95.",
    "DBA operations and DC facilities costs use rate-card assumptions (flagged Low quality).",
    "Savings are recurring annual run-cost deltas; one-time costs are shown separately.",
    "Oracle on Azure follows the authorised-cloud policy (2 vCPU = 1 processor, no core factor).",
]


@dataclass
class OptionResult:
    option: str
    status: str = "Feasible"
    target_platform: str = ""
    current_annual: float = 0.0
    target_annual: float = 0.0
    licence_saving: float = 0.0
    one_time_cost: float = 0.0
    components: dict = field(default_factory=dict)
    score: float = 0.0
    drivers: list = field(default_factory=list)
    constraints: list = field(default_factory=list)
    conditions: list = field(default_factory=list)

    @property
    def annual_saving(self) -> float:
        return self.current_annual - self.target_annual

    def block(self, reason: str):
        self.constraints.append(reason)
        if self.status != "Not feasible":
            self.status = "Blocked"

    def infeasible(self, reason: str):
        self.constraints.append(reason)
        self.status = "Not feasible"

    def condition(self, reason: str):
        self.conditions.append(reason)
        if self.status == "Feasible":
            self.status = "Conditional"


def complexity(i: dict) -> float:
    size = min(10.0, float(i["db_size_gb"]) / 400)
    links = min(15, int(i["db_links_or_linked_servers"]) * 4)
    if i["db_engine"] == "Oracle":
        return round(min(40, i["code_objects"] / 60) + links + (15 if str(i["cluster_type"]).startswith("RAC") else 0)
                     + (10 if i["character_set_or_collation"] != "AL32UTF8" else 0)
                     + (10 if i["uses_java_or_aq"] else 0) + size, 1)
    return round(min(35, i["code_objects"] / 60) + links + (10 if i["uses_clr"] else 0) + (10 if i["uses_filestream"] else 0)
                 + (8 if i["uses_ssis"] else 0) + (5 if i["uses_cross_db_queries"] else 0) + size, 1)


def rightsize(vcpus: int, cpu_p95: float, minimum: int = 2, sizes: list[int] | None = None) -> int:
    need = max(minimum, math.ceil(vcpus * (cpu_p95 / 100) / RIGHTSIZE_TARGET_UTILISATION))
    need += need % 2
    if sizes:
        return next((s for s in sizes if s >= need), sizes[-1])
    return need


class DecisionEngine:
    def __init__(self, data: dict[str, pd.DataFrame], risk: pd.DataFrame, dep_profiles: pd.DataFrame,
                 oracle_discovery_available: bool = True):
        self.inst = data["database_instances"]
        self.work = data["workload_metrics"].set_index("instance_id")
        self.rec = data["recovery_requirements"].set_index("instance_id")
        self.apps = data["applications"].set_index("application_id")
        self.feat = data["feature_usage"]
        costs = data["cost_records"]
        self.costs = costs.pivot_table(index="instance_id", columns="cost_type", values="annual_cost_gbp", aggfunc="sum").fillna(0)
        self.risk = risk.set_index("instance_id")
        self.deps = dep_profiles.set_index("instance_id")
        self.oracle_ok = oracle_discovery_available
        self._peers = self._consolidation_pools()

    # ------------------------------------------------------------------ helpers
    def _low_util(self, iid: str) -> bool:
        w = self.work.loc[iid]
        return w.cpu_p95_pct <= CONSOLIDATION_CPU_P95_MAX and w.memory_used_pct <= CONSOLIDATION_MEM_MAX and w.connections_90d > 0

    def _consolidation_pools(self) -> dict[str, list[str]]:
        pools: dict[tuple, list[str]] = {}
        for i in self.inst.itertuples():
            tier = self.rec.loc[i.instance_id, "criticality_tier"]
            eligible_env = i.environment != "Production" or tier == "Tier 3"
            if eligible_env and self._low_util(i.instance_id) and i.business_service:
                # Same-version pools consolidate without a forced upgrade
                key = (i.db_engine, i.major_version, i.environment, i.business_service, i.data_residency)
                pools.setdefault(key, []).append(i.instance_id)
        return {iid: members for members in pools.values() if len(members) > 1 for iid in members}

    def _features(self, iid: str) -> pd.DataFrame:
        return self.feat[self.feat.instance_id == iid]

    def _evidence(self, i: dict) -> tuple[list[dict], float]:
        iid = i["instance_id"]
        stale = i["db_engine"] == "Oracle" and not self.oracle_ok
        disc_q = "Missing" if not i["discovery_source_ref"] else ("Low (stale snapshot)" if stale else "High")
        w = self.work.loc[iid]
        r = self.rec.loc[iid]
        d = self.deps.loc[iid]
        feats = self._features(iid)
        feat_q = disc_q if disc_q != "High" else ("Medium" if (feats.evidence_quality == "Medium").any() else "High")
        lc = self.risk.loc[iid]
        items = [
            dict(evidence_type="Inventory & configuration", weight=0.25, quality=disc_q,
                 source=(i["discovery_source_ref"] or "CMDB record only (unverified)"),
                 fact=f"{i['db_engine']} {i['version_build']} {i['edition']} | {i['physical_cores']} cores / {i['memory_gb']} GB | "
                      f"{i['server_type']} | {i['ha_dr_config']}", collected_at=i["collected_at"]),
            dict(evidence_type="Vendor lifecycle", weight=0.0, quality="High", source="Vendor lifecycle catalogue (reference.py)",
                 fact=f"{lc.lifecycle_status}; extended support end {lc.support_end}", collected_at=ASSESSMENT_DATE.isoformat()),
            dict(evidence_type="Workload utilisation", weight=0.15, quality=("Low (stale snapshot)" if stale else w.evidence_quality),
                 source=w.source, fact=f"CPU p95 {w.cpu_p95_pct}% | memory {w.memory_used_pct}% | {w.connections_90d:,} connections/90d"
                 f" | last connection {w.last_connection_date}", collected_at=w.collected_at),
            dict(evidence_type="Feature usage", weight=0.15, quality=feat_q,
                 source="DBA_FEATURE_USAGE_STATISTICS" if i["db_engine"] == "Oracle" else "sys.dm_db_persisted_sku_features",
                 fact=("Options detected: " + ", ".join(sorted(set(feats.product_option)))) if len(feats) else "No licensable options detected",
                 collected_at=i["collected_at"]),
            dict(evidence_type="Dependencies", weight=0.20, quality=d.dependency_evidence_quality, source=i["dependency_evidence"],
                 fact=(f"{d.active_dependants} active dependant(s), {d.upstream_dependencies} upstream"
                       if d.dependencies_known else "No dependency evidence collected"), collected_at=""),
            dict(evidence_type="Recovery requirements", weight=0.15, quality=r.evidence_quality, source=r.source,
                 fact=(f"{r.criticality_tier}; RPO {r.rpo_minutes:g} min / RTO {r.rto_minutes:g} min"
                       if not pd.isna(r.rpo_minutes) else f"{r.criticality_tier}; RPO/RTO not recorded"), collected_at=""),
            dict(evidence_type="Cost", weight=0.10, quality="Medium", source="Finance chargeback / contract register FY26",
                 fact=f"Current annual run cost £{self.costs.loc[iid].sum():,.0f}", collected_at=""),
        ]
        conf = sum(e["weight"] * QUALITY.get(e["quality"], 0.4) for e in items)
        return items, round(conf * 100, 1)

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, i: dict) -> tuple[list[OptionResult], dict]:
        iid = i["instance_id"]
        c = self.costs.loc[iid].to_dict()
        current = sum(c.values())
        cur_lic = sum(c.get(k, 0) for k in LIC_LINES)
        w = self.work.loc[iid]
        r = self.rec.loc[iid]
        d = self.deps.loc[iid]
        lc = self.risk.loc[iid]
        cx = complexity(i)
        feats = self._features(iid)
        app = self.apps.loc[i["application_id"]] if i["application_id"] in self.apps.index else None
        certified = str(app.certified_db_versions) if app is not None else "Unknown"
        deps_known = bool(d.dependencies_known)
        rec_known = not pd.isna(r.rpo_minutes)
        stale = i["db_engine"] == "Oracle" and not self.oracle_ok
        prod = i["environment"] == "Production"
        unsupported = lc.lifecycle_status == "Unsupported"
        eos_risk = {"Unsupported": 100, "Approaching EOS": 80, "Extended Support": 60}.get(lc.lifecycle_status, 50)
        os_eos = (ref.OS_LIFECYCLE.get(i["os_platform"]) or ASSESSMENT_DATE) < ASSESSMENT_DATE
        idle_days = (ASSESSMENT_DATE - pd.Timestamp(w.last_connection_date).date()).days
        regions = ref.AZURE_ALLOWED_REGIONS.get(i["data_residency"], [])
        hi_avail = rec_known and (r.rpo_minutes <= 5 or r.rto_minutes <= 60)

        def common(o: OptionResult):
            if not i["owner"]:
                o.condition("Accountable owner not recorded")
            if stale and o.option != "Retain":
                o.condition("Oracle discovery collector unavailable - using last-known snapshot")

        def migration_gates(o: OptionResult, needs_recovery: bool = True):
            if not deps_known:
                o.block("Dependencies unknown - cannot confirm impact (hard constraint)")
            if needs_recovery and not rec_known:
                o.block("RPO/RTO unknown - recovery design cannot be validated (hard constraint)")

        results: list[OptionResult] = []

        # 1. Retain ----------------------------------------------------------
        o = OptionResult("Retain", target_platform="As-is", current_annual=current, target_annual=current)
        o.components = dict(value=0, risk_reduction={"Unsupported": 0, "Approaching EOS": 25, "Extended Support": 40}.get(lc.lifecycle_status, 50),
                            feasibility=100, strategic_fit=20)
        o.drivers.append("No change - existing risks and costs persist")
        if unsupported:
            o.drivers.append(f"Remains on unsupported {i['major_version']}")
        results.append(o)

        # 2. Upgrade ---------------------------------------------------------
        target = lc.upgrade_target if isinstance(lc.upgrade_target, str) else None
        o = OptionResult("Upgrade", target_platform=f"{i['db_engine']} {target}" if target else "", current_annual=current)
        if not target:
            o.infeasible("Already on latest long-term release")
        else:
            o.target_annual = current - c.get("extended_security_updates", 0) - c.get("sustaining_support_uplift", 0) - 0.1 * c.get("dba_operations", 0)
            o.licence_saving = c.get("extended_security_updates", 0) + c.get("sustaining_support_uplift", 0)
            o.one_time_cost = ref.ONE_TIME_COST["Upgrade"][0] + ref.ONE_TIME_COST["Upgrade"][1] * cx + (8000 if os_eos else 0)
            short = target.split(" (")[0]
            cert_token = f"Oracle {short.split(' ')[0]}" if i["db_engine"] == "Oracle" else short
            if cert_token not in certified:
                o.condition(f"Application certification for {cert_token} not confirmed (certified: {certified})")
            if not rec_known:
                o.condition("RPO/RTO unknown - downtime and rollback window cannot be validated")
            o.drivers.append(f"Direct upgrade path {i['major_version']} -> {target} supported"
                             + (" (AutoUpgrade)" if i["db_engine"] == "Oracle" else " (in-place or side-by-side)"))
            if o.licence_saving:
                o.drivers.append(f"Removes ESU / sustaining support premium £{o.licence_saving:,.0f}/yr")
            if os_eos:
                o.drivers.append(f"OS {i['os_platform']} also out of support - side-by-side build on new OS")
            if i["db_engine"] == "Oracle" and "23ai" in target and int(i["pdb_count"]) == 0:
                o.condition("Non-CDB must be converted to multitenant (PDB) for 23ai")
            o.components = dict(risk_reduction=eos_risk, feasibility=75 - cx / 4, strategic_fit=50)
        results.append(o)

        # 3. Consolidate -----------------------------------------------------
        o = OptionResult("Consolidate", current_annual=current)
        peers = self._peers.get(iid, [])
        if not peers:
            o.infeasible("No low-utilisation peer in same engine / environment / service / residency pool"
                         if self._low_util(iid) else f"Utilisation too high for consolidation (CPU p95 {w.cpu_p95_pct}%)")
        else:
            n = len(peers)
            o.target_platform = f"Shared {i['db_engine']} host ({n} instances, pool {i['business_service']}/{i['environment']})"
            o.target_annual = current * (1 - 0.8 * (n - 1) / n)
            o.licence_saving = cur_lic * 0.8 * (n - 1) / n
            o.one_time_cost = ref.ONE_TIME_COST["Consolidate"][0] + ref.ONE_TIME_COST["Consolidate"][1] * cx
            o.drivers.append(f"Pool of {n} low-utilisation {i['major_version']} instances (CPU p95 <= {CONSOLIDATION_CPU_P95_MAX}%): {', '.join(peers)}")
            migration_gates(o)
            o.components = dict(risk_reduction=70 if unsupported else 50, feasibility=80 - cx / 5, strategic_fit=60)
        results.append(o)

        # 4. Replatform (edition change or engine change) ----------------------
        variants: list[OptionResult] = []
        fit = edition_fit(i, feats)
        if fit.get("candidate"):
            v = OptionResult("Replatform", target_platform=f"{i['db_engine']} {fit['target']}", current_annual=current)
            saving = edition_downgrade_saving(i)
            v.target_annual = current - saving
            v.licence_saving = saving
            v.one_time_cost = ref.ONE_TIME_COST["Replatform-Edition"][0] + ref.ONE_TIME_COST["Replatform-Edition"][1] * cx
            v.drivers.append(f"No higher-edition features in use; fits {fit['target']} limits - saves £{saving:,.0f}/yr support")
            for cond in fit["conditions"]:
                v.condition(cond)
            migration_gates(v)
            v.components = dict(risk_reduction=70 if unsupported else 50, feasibility=85 - cx / 5, strategic_fit=60)
            variants.append(v)
        if i["db_engine"] == "SQL Server" and not prod and i["edition"] in ("Enterprise", "Standard"):
            v = OptionResult("Replatform", target_platform="SQL Server Developer edition (non-production)", current_annual=current)
            v.target_annual = current - c.get("licence_support", 0)
            v.licence_saving = c.get("licence_support", 0)
            v.one_time_cost = 3000 + 50 * cx
            v.condition("Confirm environment holds no production data / workload (Developer licence terms)")
            v.drivers.append(f"Non-production paid edition - Developer edition removes £{v.licence_saving:,.0f}/yr SA")
            migration_gates(v)
            v.components = dict(risk_reduction=50, feasibility=90, strategic_fit=55)
            variants.append(v)
        if i["db_engine"] == "Oracle":
            v = OptionResult("Replatform", target_platform="Azure Database for PostgreSQL (Flexible Server)", current_annual=current)
            if i["code_objects"] > PG_REPLATFORM_MAX_PLSQL_OBJECTS:
                v.infeasible(f"{i['code_objects']} PL/SQL objects > {PG_REPLATFORM_MAX_PLSQL_OBJECTS} conversion threshold")
            if str(i["cluster_type"]).startswith("RAC"):
                v.infeasible("RAC workload - not a PostgreSQL replatform candidate")
            if i["uses_java_or_aq"]:
                v.infeasible("Uses Java-in-DB / Advanced Queuing")
            if not regions:
                v.infeasible(f"Data residency '{i['data_residency']}' prohibits cloud hosting")
            vc = rightsize(i["vcpus"], w.cpu_p95_pct)
            ha_factor = 2 if hi_avail else 1
            v.target_annual = (vc * ref.AZURE_RATES["Azure Database for PostgreSQL (Flexible)"] * 12 * ha_factor
                               + float(i["db_size_gb"]) * ref.AZURE_STORAGE_GB_YEAR * 1.3 + 0.6 * c.get("dba_operations", 0))
            v.licence_saving = cur_lic
            v.one_time_cost = ref.ONE_TIME_COST["Replatform-Engine"][0] + 25 * i["code_objects"] + 6 * float(i["db_size_gb"])
            v.drivers.append(f"Oracle licence eliminated; {vc} vCore PostgreSQL Flexible" + (" zone-redundant HA" if hi_avail else ""))
            v.condition("Code conversion assessment (ora2pg) and application regression testing required")
            if "PostgreSQL" not in certified:
                v.condition("Application not certified on PostgreSQL")
            if "PCI" in i["data_classification"] and not AZURE_PCI_LANDING_ZONE_APPROVED:
                v.condition("PCI-DSS Azure landing zone not yet approved")
            migration_gates(v)
            v.components = dict(risk_reduction=eos_risk if unsupported else 50, feasibility=55 - cx / 2, strategic_fit=70)
            variants.append(v)
        if variants:
            for v in variants:
                self._score(v)
            ranked = sorted(variants, key=lambda x: (x.status != "Not feasible", x.score), reverse=True)
            results.append(ranked[0])
        else:
            o = OptionResult("Replatform", current_annual=current)
            o.infeasible("Higher-edition features in use / no viable edition or engine change")
            results.append(o)

        # 5. Cloud Migrate (Azure) --------------------------------------------
        o = OptionResult("Cloud Migrate", current_annual=current)
        if not regions:
            o.infeasible(f"Data residency '{i['data_residency']}' - no approved Azure region (hard constraint)")
        needs_upgrade = lc.lifecycle_status in ("Unsupported", "Approaching EOS")
        if i["db_engine"] == "SQL Server":
            iaas = bool(i["uses_filestream"] or i["uses_clr"] or i["uses_ssis"])
            if iaas:
                target = "SQL Server on Azure VM"
                vc = rightsize(i["vcpus"], w.cpu_p95_pct, minimum=4)
                lic = max(4, vc) * ref.SQL_EDITION_PRICE_PER_CORE.get(i["edition"], 0) * ref.SQL_SA_RATE
                o.target_annual = (vc * ref.AZURE_RATES[target] * 12 * (2 if hi_avail else 1) + lic
                                   + float(i["storage_allocated_gb"]) * ref.AZURE_STORAGE_GB_YEAR + 0.85 * c.get("dba_operations", 0))
                o.licence_saving = cur_lic - lic
                o.drivers.append(f"FILESTREAM/CLR/SSIS present -> IaaS; free ESUs on Azure VM; {vc} vCPU right-sized")
                o.one_time_cost = ref.ONE_TIME_COST["Cloud Migrate-IaaS"][0] + 250 * cx + 2 * float(i["db_size_gb"])
            else:
                mi = bool(i["uses_cross_db_queries"] or i["uses_sql_agent_jobs"] or i["db_links_or_linked_servers"])
                bc = rec_known and (r.rpo_minutes == 0 or r.rto_minutes <= 15)
                target = ("Azure SQL Managed Instance (BC)" if bc else "Azure SQL Managed Instance (GP)") if mi else "Azure SQL Database (GP)"
                vc = rightsize(i["vcpus"], w.cpu_p95_pct, minimum=4 if mi else 2, sizes=ref.MI_VCORE_SIZES if mi else None)
                li = vc * ref.AZURE_RATES[target] * 12
                ahb = li * ref.AHB_DISCOUNT + c.get("licence_support", 0) if i["edition"] in ("Enterprise", "Standard") else li
                compute = min(li, ahb)
                o.target_annual = compute + float(i["db_size_gb"]) * ref.AZURE_STORAGE_GB_YEAR + 0.5 * c.get("dba_operations", 0)
                o.licence_saving = c.get("extended_security_updates", 0)
                o.drivers.append(f"{target}: {vc} vCores right-sized from CPU p95 {w.cpu_p95_pct}% "
                                 f"({'Azure Hybrid Benefit' if ahb < li else 'licence-included'} pricing); evergreen version")
                if mi:
                    o.drivers.append("Managed Instance chosen for cross-DB queries / SQL Agent / linked servers")
                o.one_time_cost = ref.ONE_TIME_COST["Cloud Migrate-PaaS"][0] + 500 * cx + 4 * float(i["db_size_gb"])
                needs_upgrade = False  # PaaS is evergreen
            o.target_platform = f"{target} ({regions[0] if regions else 'n/a'})"
        else:
            if str(i["cluster_type"]).startswith("RAC"):
                target = "Oracle Database@Azure (Exadata)"
                vc = max(16, rightsize(i["vcpus"], w.cpu_p95_pct))
                infra = vc * ref.AZURE_RATES[target] * 12
                procs = oracle_processors(i)
                o.drivers.append("RAC is not supported on Azure VMs - Oracle Database@Azure (Exadata) required")
            else:
                target = "Oracle on Azure VM (BYOL)"
                vc = rightsize(i["vcpus"], w.cpu_p95_pct)
                infra = vc * ref.AZURE_RATES[target] * 12 * (2 if hi_avail else 1)
                procs = max(1, math.ceil(vc / 2))
                o.drivers.append(f"{vc} vCPU constrained VM; authorised-cloud policy -> {procs} processor licence(s) "
                                 f"vs {oracle_processors(i)} on-prem")
            cur_procs = oracle_processors(i)
            lic = c.get("licence_support", 0) * (procs / cur_procs if i["edition"] == "Enterprise Edition" else 1)
            o.target_annual = infra + lic + float(i["storage_allocated_gb"]) * ref.AZURE_STORAGE_GB_YEAR + 0.85 * c.get("dba_operations", 0)
            o.licence_saving = cur_lic - lic
            o.one_time_cost = ref.ONE_TIME_COST["Cloud Migrate-IaaS"][0] + 250 * cx + 2 * float(i["db_size_gb"])
            o.target_platform = f"{target} ({regions[0] if regions else 'n/a'})"
        if needs_upgrade:
            o.one_time_cost += ref.ONE_TIME_COST["Upgrade"][0] + ref.ONE_TIME_COST["Upgrade"][1] * cx
            o.target_annual -= c.get("sustaining_support_uplift", 0)
            o.drivers.append(f"Includes upgrade to {lc.upgrade_target or 'current release'} during migration")
        if "PCI" in i["data_classification"] and not AZURE_PCI_LANDING_ZONE_APPROVED and regions:
            o.condition("PCI-DSS Azure landing zone not yet approved")
        migration_gates(o)
        paas = "Azure SQL" in o.target_platform
        # PaaS is evergreen (resolves EOS); IaaS only resolves EOS when an upgrade is bundled in,
        # and bundling migration + upgrade in one change carries extra delivery risk.
        rr = max(eos_risk, 55) if paas else (80 if needs_upgrade else 50)
        feas = (65 - cx / 3) if paas else (75 - cx / 4 - (10 if needs_upgrade else 0))
        o.components = dict(risk_reduction=rr, feasibility=feas,
                            strategic_fit=60 if "Exadata" in o.target_platform else 80)
        results.append(o)

        # 6. Retire ------------------------------------------------------------
        o = OptionResult("Retire", target_platform="Decommission + archive", current_annual=current, target_annual=600)
        if w.connections_90d > 0 or idle_days < RETIRE_IDLE_DAYS:
            o.infeasible(f"Active workload ({w.connections_90d:,} connections in 90 days)")
        elif deps_known and d.active_dependants > 0:
            o.infeasible(f"{d.active_dependants} active dependant(s): {d.dependants}")
        else:
            o.drivers.append(f"No connections for {idle_days} days; no active dependants")
            o.licence_saving = cur_lic
            if prod:
                o.condition("Production retirement - owner sign-off and data-retention / archival check required")
        o.one_time_cost = ref.ONE_TIME_COST["Retire"][0] + float(i["db_size_gb"])
        migration_gates(o, needs_recovery=False)
        o.components = dict(risk_reduction=100 if unsupported else 70, feasibility=90, strategic_fit=90)
        results.append(o)

        for o in results:
            common(o)
            self._score(o)
        # Value gate: a change with no positive 5-year case only beats Retain if it fixes an unsupported / near-EOS version.
        retain_score = results[0].score
        lifecycle_driver = lc.lifecycle_status in ("Unsupported", "Approaching EOS")
        for o in results[1:]:
            resolves_eos = lifecycle_driver and o.components.get("risk_reduction", 0) > 55
            if o.status != "Not feasible" and o.components.get("value", 0) == 0 and not resolves_eos:
                if o.score >= retain_score:
                    o.score = round(retain_score - 0.1, 1)
                o.drivers.append("Value gate: no positive 5-year business case and no lifecycle risk resolved")
        evidence, confidence = self._evidence(i)
        return results, dict(evidence=evidence, confidence_pct=confidence, complexity=cx)

    @staticmethod
    def _score(o: OptionResult) -> None:
        if o.status == "Not feasible":
            o.score = 0.0
            return
        if o.option != "Retain":
            net5 = 5 * o.annual_saving - o.one_time_cost
            o.components["value"] = round(max(0.0, min(1.0, net5 / (5 * o.current_annual))) * 100, 1) if o.current_annual else 0
        o.components = {k: round(max(0.0, float(v)), 1) for k, v in o.components.items()}
        o.score = round(sum(o.components.get(k, 0) * wt for k, wt in WEIGHTS.items()), 1)

    # ------------------------------------------------------------------ portfolio
    def run(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        recs, options, evidence = [], [], []
        for i in self.inst.to_dict("records"):
            results, meta = self.evaluate(i)
            for o in results:
                options.append(dict(instance_id=i["instance_id"], option=o.option, status=o.status, score=o.score,
                                    target_platform=o.target_platform, current_annual=round(o.current_annual, 2),
                                    target_annual=round(o.target_annual, 2), annual_saving=round(o.annual_saving, 2),
                                    licence_saving=round(o.licence_saving, 2), one_time_cost=round(o.one_time_cost, 2),
                                    **{f"c_{k}": v for k, v in o.components.items()},
                                    drivers=" | ".join(o.drivers), constraints=" | ".join(o.constraints),
                                    conditions=" | ".join(o.conditions)))
            viable = [o for o in results if o.status != "Not feasible"]
            best = max(viable, key=lambda o: o.score)
            alt = sorted((o for o in viable if o is not best), key=lambda o: o.score, reverse=True)
            readiness = {"Feasible": "Ready", "Conditional": "Conditional", "Blocked": "Blocked"}[best.status]
            conf = meta["confidence_pct"]
            band = "High" if conf >= 80 else "Medium" if conf >= 60 else "Low"
            net5 = 5 * best.annual_saving - best.one_time_cost
            rationale = best.drivers[:]
            if best.option != "Retain" and net5 < 0:
                rationale.insert(0, f"Risk-driven: 5-yr net £{net5:,.0f} is negative - justified by lifecycle/security risk, not savings")
            if best.status == "Blocked":
                nxt = "Close evidence gaps first: " + "; ".join(best.constraints)
            elif best.status == "Conditional":
                nxt = "Human review of conditions: " + "; ".join(best.conditions)
            elif best.option == "Retain":
                nxt = "No action - re-assess at next review cycle"
            else:
                nxt = f"Submit to Architecture & Licensing board for approval of {best.option}"
            rec_id = f"REC-{i['instance_id']}"
            recs.append(dict(recommendation_id=rec_id, instance_id=i["instance_id"], db_engine=i["db_engine"],
                             environment=i["environment"], business_service=i["business_service"],
                             recommended_action=best.option, target_platform=best.target_platform, readiness=readiness,
                             score=best.score, runner_up=(alt[0].option if alt else ""), runner_up_score=(alt[0].score if alt else 0),
                             current_annual=round(best.current_annual, 2), target_annual=round(best.target_annual, 2),
                             annual_saving=round(best.annual_saving, 2), licence_saving=round(best.licence_saving, 2),
                             one_time_cost=round(best.one_time_cost, 2),
                             payback_months=(round(best.one_time_cost / (best.annual_saving / 12), 1) if best.annual_saving > 0 and best.one_time_cost else None),
                             net_5yr=round(5 * best.annual_saving - best.one_time_cost, 2),
                             confidence_pct=conf, confidence=band, complexity=meta["complexity"],
                             rationale=" | ".join(rationale), constraints=" | ".join(best.constraints),
                             conditions=" | ".join(best.conditions), next_action=nxt,
                             assumptions=" | ".join(ASSUMPTIONS), human_decision="Pending",
                             approval_required=("Architecture + Licensing + Service owner" if best.option != "Retain" else "Service owner (acknowledge)")))
            for e in meta["evidence"]:
                evidence.append(dict(recommendation_id=rec_id, instance_id=i["instance_id"],
                                     **{k: v for k, v in e.items() if k != "weight"}))
        rec_df = pd.DataFrame(recs)
        log.info("Decision engine: %s", rec_df.recommended_action.value_counts().to_dict())
        return rec_df, pd.DataFrame(options), pd.DataFrame(evidence)
