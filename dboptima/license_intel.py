"""Module 2 - Licence intelligence.

Produces an INDICATIVE licence position and optimisation opportunities. It never declares
legal compliance: every finding is flagged for validation by a licensing SME using
authoritative contract evidence.
"""
from __future__ import annotations

import pandas as pd

from . import reference as ref
from .data_generator import oracle_processors, required_licences, sql_licensable_cores
from .config import get_logger

log = get_logger("license_intel")

DISCLAIMER = ("Indicative position derived from discovery evidence and list prices. Not a compliance determination - "
              "requires validation by a licensing SME against contracts before any commercial action.")


def sql_enterprise_features_in_use(feature_rows: pd.DataFrame, major_version: str) -> list[str]:
    """Return features that genuinely require Enterprise edition for the given SQL Server version."""
    needed = []
    idx = ref.SQL_VERSION_ORDER.index(major_version) if major_version in ref.SQL_VERSION_ORDER else 0
    for f in feature_rows.loc[feature_rows.currently_used.astype(bool), "feature_name"]:
        rule = ref.SQL_ENTERPRISE_FEATURES.get(f)
        if not rule:
            continue
        if rule.get("enterprise_only"):
            needed.append(f)
        elif "enterprise_only_before" in rule and idx < ref.SQL_VERSION_ORDER.index(rule["enterprise_only_before"]):
            needed.append(f)
    return needed


def edition_fit(inst: dict, feature_rows: pd.DataFrame) -> dict:
    """Assess whether a lower edition could run this workload (technical fit only)."""
    if inst["db_engine"] == "Oracle":
        if inst["edition"] != "Enterprise Edition":
            return {"candidate": False}
        current = feature_rows[feature_rows.currently_used.astype(bool)] if len(feature_rows) else feature_rows
        options = sorted(set(current["product_option"])) if len(current) else []
        blockers = []
        if options:
            blockers.append(f"EE options in use: {', '.join(options)}")
        if inst["cpu_sockets"] > ref.SE2_MAX_SOCKETS:
            blockers.append(f"{inst['cpu_sockets']} sockets > SE2 limit of {ref.SE2_MAX_SOCKETS}")
        if inst["vcpus"] > ref.SE2_MAX_THREADS:
            blockers.append(f"{inst['vcpus']} threads > SE2 limit of {ref.SE2_MAX_THREADS}")
        if str(inst["cluster_type"]).startswith("RAC"):
            blockers.append("RAC not available on SE2 (19c+)")
        conditions = []
        if "Data Guard" in str(inst["ha_dr_config"]):
            conditions.append("Data Guard is EE-only - replace with Dbvisit Standby / storage replication")
        return {"candidate": not blockers, "target": "Standard Edition 2", "blockers": blockers, "conditions": conditions}
    if inst["edition"] != "Enterprise":
        return {"candidate": False}
    ent = sql_enterprise_features_in_use(feature_rows, inst["major_version"])
    blockers = [f"Enterprise-only feature in use: {f}" for f in ent]
    if inst["physical_cores"] > ref.SQL_STD_MAX_CORES:
        blockers.append(f"{inst['physical_cores']} cores > Standard limit of {ref.SQL_STD_MAX_CORES}")
    if inst["memory_gb"] > ref.SQL_STD_MAX_MEMORY_GB:
        blockers.append(f"{inst['memory_gb']} GB RAM > Standard buffer-pool limit of {ref.SQL_STD_MAX_MEMORY_GB} GB")
    conditions = []
    if "Always On AG" in str(inst["ha_dr_config"]):
        conditions.append("Standard supports Basic AG only (1 database per AG, no readable secondary)")
    return {"candidate": not blockers, "target": "Standard", "blockers": blockers, "conditions": conditions}


def edition_downgrade_saving(inst: dict) -> float:
    if inst["db_engine"] == "Oracle":
        ee = oracle_processors(inst) * ref.ORACLE_EDITION_PRICE["Enterprise Edition"]
        se2 = inst["cpu_sockets"] * ref.ORACLE_EDITION_PRICE["Standard Edition 2"]
        return (ee - se2) * ref.ORACLE_SUPPORT_RATE
    cores = sql_licensable_cores(inst)
    return cores * (ref.SQL_EDITION_PRICE_PER_CORE["Enterprise"] - ref.SQL_EDITION_PRICE_PER_CORE["Standard"]) * ref.SQL_SA_RATE


def licence_position(entitlements: pd.DataFrame, instances: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    discovered = instances[instances.discovery_source_ref != ""]
    req = required_licences(discovered, features)
    rows = []
    for e in entitlements.itertuples():
        required = req.get(e.product, {}).get("quantity", 0)
        delta = e.quantity - required
        unit_support = e.unit_list_price_gbp * e.support_rate
        if delta > 0:
            status = "Surplus - optimisation candidate"
        elif delta < 0:
            status = "Potential shortfall - validate (not a compliance finding)"
        else:
            status = "Balanced"
        rows.append(dict(entitlement_id=e.entitlement_id, vendor=e.vendor, product=e.product, metric=e.metric,
                         entitled=e.quantity, deployed_requirement=required, delta=delta, status=status,
                         annual_support_gbp=e.annual_support_gbp,
                         surplus_support_gbp=round(max(delta, 0) * unit_support, 2),
                         exposure_list_value_gbp=round(max(-delta, 0) * e.unit_list_price_gbp, 2),
                         agreement_ref=e.agreement_ref, renewal_date=e.support_renewal_date))
    return pd.DataFrame(rows)


def instance_findings(instances: pd.DataFrame, features: pd.DataFrame, oracle_discovery_available: bool = True) -> pd.DataFrame:
    rows = []
    feats = features.groupby("instance_id")
    for inst in instances.to_dict("records"):
        iid = inst["instance_id"]
        fr = feats.get_group(iid) if iid in feats.groups else features.iloc[0:0]
        stale = inst["db_engine"] == "Oracle" and not oracle_discovery_available

        def add(category, finding, value, quality, action):
            rows.append(dict(instance_id=iid, db_engine=inst["db_engine"], environment=inst["environment"],
                             edition=inst["edition"], category=category, finding=finding,
                             est_annual_value_gbp=round(value, 2), evidence_quality="Low (stale snapshot)" if stale else quality,
                             recommended_action=action, requires_human_validation=True))

        if not inst["discovery_source_ref"]:
            add("Evidence gap", "Feature usage not collected - instance not reached by discovery collector", 0, "Missing",
                "Fix collector coverage / credentials before any licence decision")
            continue
        fit = edition_fit(inst, fr)
        if fit.get("candidate"):
            cond = f" Conditions: {'; '.join(fit['conditions'])}." if fit["conditions"] else ""
            add("Edition optimisation", f"{inst['edition']} with no higher-edition features in use - fits {fit['target']}.{cond}",
                edition_downgrade_saving(inst), "High", f"Validate & plan edition change to {fit['target']}")
        if inst["db_engine"] == "SQL Server" and inst["environment"] != "Production" and inst["edition"] in ("Enterprise", "Standard"):
            saving = sql_licensable_cores(inst) * ref.SQL_EDITION_PRICE_PER_CORE[inst["edition"]] * ref.SQL_SA_RATE
            add("Non-production licensing", "Paid edition in non-production - Developer edition (or VS subscription) may apply",
                saving, "High", "Confirm no production data/usage, then switch to Developer edition")
        if len(fr):
            historic = fr[~fr.currently_used.astype(bool)]
            for f in historic.itertuples():
                add("Audit exposure", f"Historic usage of {f.product_option} ({f.feature_name}) last seen {f.last_usage_date}",
                    0, f.evidence_quality, "Confirm licence or document remediation; disable via CONTROL_MANAGEMENT_PACK_ACCESS / parameters")
            if inst["db_engine"] == "Oracle" and inst["edition"] == "Standard Edition 2":
                for f in fr.itertuples():
                    add("Potential exposure", f"{f.product_option} usage detected on SE2 - EE options cannot be licensed on SE2",
                        0, f.evidence_quality, "Validate (possible OEM default job false positive); disable pack access")
        if inst["db_engine"] == "Oracle" and inst["server_type"] == "VMware VM" and inst["edition"] == "Enterprise Edition":
            exposure = oracle_processors(inst, use_cluster=True) - oracle_processors(inst)
            add("Virtualisation exposure", f"Oracle EE on VMware (soft partitioning): cluster of {inst['cluster_physical_cores']} cores "
                f"may imply {exposure} additional processors", 0, "Medium",
                "Licensing SME to review host affinity / dedicated cluster or move to Azure (authorised cloud policy)")
    return pd.DataFrame(rows)
