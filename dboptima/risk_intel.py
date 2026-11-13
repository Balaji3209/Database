"""Module 4 - Risk intelligence: explainable, rules-based risk scoring per instance."""
from __future__ import annotations

from datetime import date

import pandas as pd

from . import reference as ref
from .config import ASSESSMENT_DATE, EOS_WARNING_MONTHS, get_logger

log = get_logger("risk_intel")

RISK_WEIGHTS = {"Lifecycle": 0.25, "Availability": 0.15, "Recoverability": 0.20, "Security": 0.15,
                "Licence": 0.10, "Evidence": 0.15}


def lifecycle_status(engine: str, major: str, on: date = ASSESSMENT_DATE) -> dict:
    info = ref.LIFECYCLE.get(engine, {}).get(major)
    if not info:
        return {"status": "Unknown", "extended_end": None, "months_left": None, "upgrade_target": None}
    end = info["extended_end"]
    months = (end.year - on.year) * 12 + (end.month - on.month)
    if end < on:
        status = "Unsupported"
    elif months <= EOS_WARNING_MONTHS:
        status = "Approaching EOS"
    elif info["mainstream_end"] < on:
        status = "Extended Support"
    else:
        status = "Supported"
    return {"status": status, "extended_end": end, "months_left": months, "upgrade_target": info["upgrade_target"],
            "release_type": info["release_type"]}


def assess(instances: pd.DataFrame, recovery: pd.DataFrame, findings: pd.DataFrame, dep_profiles: pd.DataFrame) -> pd.DataFrame:
    rec = recovery.set_index("instance_id")
    deps = dep_profiles.set_index("instance_id")
    lic_issues = findings[findings.category.isin(["Audit exposure", "Potential exposure", "Virtualisation exposure"])]
    lic_count = lic_issues.groupby("instance_id").size()
    rows = []
    for i in instances.to_dict("records"):
        iid = i["instance_id"]
        reasons: list[str] = []
        scores = dict.fromkeys(RISK_WEIGHTS, 0)
        lc = lifecycle_status(i["db_engine"], i["major_version"])
        if lc["status"] == "Unsupported":
            scores["Lifecycle"] = 100
            reasons.append(f"{i['major_version']} out of vendor support since {lc['extended_end']}")
        elif lc["status"] == "Approaching EOS":
            scores["Lifecycle"] = 65
            reasons.append(f"{i['major_version']} support ends {lc['extended_end']} ({lc['months_left']} months)")
        elif lc["status"] == "Extended Support":
            scores["Lifecycle"] = 30
        os_end = ref.OS_LIFECYCLE.get(i["os_platform"])
        if os_end and os_end < ASSESSMENT_DATE:
            scores["Lifecycle"] = min(100, scores["Lifecycle"] + 25)
            reasons.append(f"OS {i['os_platform']} out of support since {os_end}")

        r = rec.loc[iid]
        tier = r["criticality_tier"]
        no_ha = str(i["ha_dr_config"]).startswith("None")
        if i["environment"] == "Production" and tier in ("Tier 0", "Tier 1") and no_ha:
            scores["Availability"] = 90
            reasons.append(f"{tier} production database without HA/DR")
        elif i["environment"] == "Production" and no_ha:
            scores["Availability"] = 40

        if pd.isna(r["rpo_minutes"]) or pd.isna(r["rto_minutes"]):
            scores["Recoverability"] = 80
            reasons.append("RPO/RTO not recorded in BIA register")
        else:
            restore_age = (ASSESSMENT_DATE - date.fromisoformat(r["last_restore_test_date"])).days
            if restore_age > 365:
                scores["Recoverability"] = 55
                reasons.append(f"Last restore test {restore_age} days ago (>365)")
            if r["rpo_minutes"] == 0 and no_ha:
                scores["Recoverability"] = 95
                reasons.append("RPO 0 required but no synchronous replication")

        if "PCI" in i["data_classification"] and lc["status"] == "Unsupported":
            scores["Security"] = 100
            reasons.append("PCI-DSS data on unsupported (unpatched) database version")
        elif lc["status"] == "Unsupported" and not i["esu_or_sustaining_support"]:
            scores["Security"] = 70
            reasons.append("No security patches (no ESU / sustaining support)")
        elif lc["status"] == "Unsupported":
            scores["Security"] = 45

        if lic_count.get(iid, 0):
            scores["Licence"] = min(100, 40 * lic_count.get(iid, 0))
            reasons.append(f"{lic_count.get(iid, 0)} licence exposure finding(s) to validate")

        gaps = []
        if not deps.loc[iid, "dependencies_known"]:
            gaps.append("dependencies")
        if pd.isna(r["rpo_minutes"]):
            gaps.append("RPO/RTO")
        if not i["owner"]:
            gaps.append("owner")
        if not i["application_id"]:
            gaps.append("application")
        if not i["discovery_source_ref"]:
            gaps.append("discovery evidence")
        scores["Evidence"] = min(100, 30 * len(gaps))
        if gaps:
            reasons.append("Missing evidence: " + ", ".join(gaps))

        overall = round(sum(scores[k] * w for k, w in RISK_WEIGHTS.items()), 1)
        band = "Critical" if overall >= 55 else "High" if overall >= 35 else "Medium" if overall >= 18 else "Low"
        rows.append(dict(instance_id=iid, lifecycle_status=lc["status"], support_end=lc["extended_end"],
                         months_to_eos=lc["months_left"], upgrade_target=lc["upgrade_target"],
                         **{f"risk_{k.lower()}": v for k, v in scores.items()}, risk_score=overall, risk_band=band,
                         risk_reasons="; ".join(reasons), evidence_gaps=", ".join(gaps)))
    df = pd.DataFrame(rows)
    log.info("Risk assessment complete: %s", df.risk_band.value_counts().to_dict())
    return df
