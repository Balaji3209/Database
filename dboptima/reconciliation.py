"""Module 1 - Estate discovery: normalisation and CMDB <-> discovery reconciliation."""
from __future__ import annotations

import re

import pandas as pd

from . import reference as ref
from .config import ASSESSMENT_DATE, get_logger

log = get_logger("reconciliation")

ENGINE_MAP = {"oracle": "Oracle", "oracle database": "Oracle", "oracle db": "Oracle",
              "ms sql": "SQL Server", "mssql": "SQL Server", "microsoft sql server": "SQL Server", "sql server": "SQL Server"}
ENV_MAP = {"prd": "Production", "prod": "Production", "production": "Production",
           "uat": "Pre-Production", "preprod": "Pre-Production", "ppe": "Pre-Production", "pre-production": "Pre-Production",
           "tst": "Test", "test": "Test", "sit": "Test", "dev": "Development", "development": "Development"}
EDITION_MAP = {"ee": "Enterprise Edition", "enterprise edition": "Enterprise Edition", "se2": "Standard Edition 2",
               "standard edition 2": "Standard Edition 2", "enterprise": "Enterprise", "std": "Standard",
               "standard": "Standard", "developer": "Developer", "express": "Express"}


def normalize_engine(value: str) -> str:
    return ENGINE_MAP.get(str(value).strip().lower(), str(value).strip())


def normalize_environment(value: str) -> str:
    return ENV_MAP.get(str(value).strip().lower(), "Unknown")


def normalize_edition(value: str, engine: str) -> str:
    v = str(value).strip().lower()
    if engine == "Oracle":
        if "enterprise" in v or v == "ee":
            return "Enterprise Edition"
        if "standard" in v or v == "se2":
            return "Standard Edition 2"
    else:
        for key in ("enterprise", "standard", "developer", "express"):
            if key in v:
                return key.capitalize()
        if v == "std":
            return "Standard"
    return EDITION_MAP.get(v, "Unknown")


def normalize_version(value: str, engine: str) -> str:
    """Map CMDB free text ('19c', '2014', '12.2') or build strings to a catalogue major version."""
    v = str(value).strip().lower()
    if engine == "Oracle" and v == "12c":
        return "12c (ambiguous R1/R2)"
    if engine == "Oracle" and v == "11g":
        return "11g R2 (11.2.0.4)"
    for major, info in ref.LIFECYCLE.get(engine, {}).items():
        family = info["family"]
        if engine == "Oracle":
            token = major.split(" ")[0].lower()  # e.g. "19c", "23ai"
            if v.startswith(family) or v == token:
                return major
        else:
            year = major.split(" ")[-1]
            if v == year or v.startswith(family + ".") or v == family:
                return major
    return f"Unrecognised ({value})"


def match_key(host: str, instance: str) -> str:
    host = re.sub(r"\..*$", "", str(host).strip().lower())
    return f"{host}\\{str(instance).strip().lower()}"


def reconcile(cmdb: pd.DataFrame, discovery: pd.DataFrame, instances: pd.DataFrame,
              discovery_available: dict[str, bool] | None = None) -> dict[str, pd.DataFrame | dict]:
    """Reconcile CMDB with discovery evidence.

    Precedence rules: discovery wins for technical facts (version, edition, cores);
    CMDB wins for business facts (owner, application, service). A pilot instance is
    "fully reconciled" when owner, application, version, edition and lifecycle status
    are all resolved from evidence.
    """
    discovery_available = discovery_available or {"Oracle": True, "SQL Server": True}
    # When a collector is down we fall back to its last-known snapshot and flag the evidence as stale.
    disc = discovery.copy()
    disc["stale_snapshot"] = disc["product"].map(lambda p: not discovery_available.get(p, True))
    if disc["stale_snapshot"].any():
        log.warning("Discovery collector unavailable for %s - %d records served from last-known snapshot",
                    [k for k, v in discovery_available.items() if not v], int(disc["stale_snapshot"].sum()))

    c = cmdb.copy()
    c["engine"] = c["db_engine"].map(normalize_engine)
    c["env_norm"] = c["environment"].map(normalize_environment)
    c["edition_norm"] = [normalize_edition(e, g) for e, g in zip(c["edition_recorded"], c["engine"])]
    c["version_norm"] = [normalize_version(v, g) for v, g in zip(c["version_recorded"], c["engine"])]
    c["key"] = [match_key(h, i) for h, i in zip(c["ci_name"], c["instance_name"])]

    d = disc.copy()
    d["engine"] = d["product"]
    d["edition_norm"] = [normalize_edition(e, g) for e, g in zip(d["edition_reported"], d["engine"])]
    d["version_norm"] = [normalize_version(v, g) for v, g in zip(d["version_build"], d["engine"])]
    d["key"] = [match_key(h, i) for h, i in zip(d["host_fqdn"], d["instance_name"])]

    dup_keys = set(c.loc[c.duplicated("key", keep=False), "key"])
    c_first = c.sort_values("last_verified", ascending=False).drop_duplicates("key")

    merged = c_first.merge(d, on="key", how="outer", suffixes=("_cmdb", "_disc"), indicator=True)
    inst_keys = {match_key(h, i): iid for h, i, iid in zip(instances.hostname, instances.instance_name, instances.instance_id)}
    merged["instance_id"] = merged["key"].map(inst_keys)

    def status(r) -> str:
        if r["_merge"] == "right_only":
            return "Discovery only (shadow / not in CMDB)"
        if r["_merge"] == "left_only":
            return "CMDB only (ghost CI)" if pd.isna(r["instance_id"]) else "CMDB only (not discovered)"
        conflicts = []
        if r["edition_norm_cmdb"] != r["edition_norm_disc"]:
            conflicts.append("edition")
        if r["version_norm_cmdb"] != r["version_norm_disc"]:
            conflicts.append("version")
        return "Matched - conflict resolved (" + ", ".join(conflicts) + ")" if conflicts else "Matched"

    merged["match_status"] = merged.apply(status, axis=1)
    merged["duplicate_ci"] = merged["key"].isin(dup_keys)
    merged["resolved_version"] = merged["version_norm_disc"].fillna(merged["version_norm_cmdb"])
    merged["resolved_edition"] = merged["edition_norm_disc"].fillna(merged["edition_norm_cmdb"])
    merged["engine"] = merged["engine_disc"].fillna(merged["engine_cmdb"])

    # Per pilot-instance reconciliation against the five required attributes
    inst = instances.set_index("instance_id")
    rows = []
    by_iid = merged.dropna(subset=["instance_id"]).set_index("instance_id")
    for iid in instances.instance_id:
        m = by_iid.loc[iid] if iid in by_iid.index else None
        if isinstance(m, pd.DataFrame):
            m = m.iloc[0]
        discovered = m is not None and m["_merge"] in ("both", "right_only")
        in_cmdb = m is not None and m["_merge"] in ("both", "left_only")
        owner_ok = bool(inst.at[iid, "owner"]) if in_cmdb else False
        app_ok = bool(inst.at[iid, "application_id"]) if in_cmdb else False
        version_ok = discovered and not str(m["version_norm_disc"]).startswith("Unrecognised")
        edition_ok = discovered and m["edition_norm_disc"] != "Unknown"
        lifecycle_ok = version_ok and inst.at[iid, "major_version"] in ref.LIFECYCLE[inst.at[iid, "db_engine"]]
        gaps = [n for n, ok in (("owner", owner_ok), ("application", app_ok), ("version", version_ok),
                                ("edition", edition_ok), ("lifecycle", lifecycle_ok)) if not ok]
        stale = bool(discovered and str(m.get("stale_snapshot")) == "True")
        rows.append(dict(instance_id=iid, db_engine=inst.at[iid, "db_engine"],
                         match_status=m["match_status"] if m is not None else "Not found",
                         duplicate_ci=bool(m["duplicate_ci"]) if m is not None else False,
                         in_cmdb=in_cmdb, discovered=discovered, fully_reconciled=not gaps,
                         evidence_freshness="Stale snapshot" if stale else ("Current" if discovered else "No discovery"),
                         unresolved_attributes=", ".join(gaps)))
    per_instance = pd.DataFrame(rows)

    exceptions = merged[(merged["match_status"] != "Matched") | merged["duplicate_ci"]].copy()
    exceptions["recommended_action"] = exceptions["match_status"].map(lambda s: (
        "Raise CMDB onboarding task; assign owner & application" if s.startswith("Discovery only") else
        "Verify server exists; mark CI decommissioned" if "ghost" in s else
        "Investigate collector coverage / credentials" if "not discovered" in s else
        "Update CMDB from discovery (discovery is authoritative for technical facts)" if "conflict" in s else
        "Merge duplicate CIs"))
    exceptions.loc[exceptions["duplicate_ci"] & (exceptions["match_status"] == "Matched"), "recommended_action"] = "Merge duplicate CIs"

    summary = {
        "pilot_instances": len(per_instance),
        "fully_reconciled": int(per_instance.fully_reconciled.sum()),
        "reconciliation_rate": round(100 * per_instance.fully_reconciled.mean(), 1),
        "matched": int((merged["_merge"] == "both").sum()),
        "conflicts_resolved": int(merged["match_status"].str.contains("conflict").sum()),
        "shadow": int(merged["match_status"].str.startswith("Discovery only").sum()),
        "ghost": int(merged["match_status"].str.contains("ghost").sum()),
        "not_discovered": int(merged["match_status"].str.contains("not discovered").sum()),
        "duplicates": int(merged.loc[merged["duplicate_ci"], "key"].nunique()),
        "stale_snapshot": int((per_instance.evidence_freshness == "Stale snapshot").sum()),
        "assessed_on": ASSESSMENT_DATE.isoformat(),
    }
    log.info("Reconciliation: %s", summary)
    cols = ["key", "instance_id", "engine", "match_status", "duplicate_ci", "ci_id", "source_ref", "version_recorded",
            "version_build", "resolved_version", "edition_recorded", "edition_reported", "resolved_edition", "recommended_action"]
    return {"per_instance": per_instance, "exceptions": exceptions[[c for c in cols if c in exceptions]],
            "merged": merged, "summary": summary}
