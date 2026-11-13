"""Module 6 - Cost optimisation, TCO simulator, budget scenario and migration waves."""
from __future__ import annotations

import pandas as pd

from .config import get_logger

log = get_logger("tco")

LEVER_OF = {"Retire": "Retire idle DBs", "Consolidate": "Consolidate low-utilisation",
            "Upgrade": "Upgrade (remove ESU/sustaining)", "Cloud Migrate": "Azure migrate & right-size",
            "Replatform": "Edition / engine replatform"}


def portfolio_tco(recs: pd.DataFrame, years: int = 5) -> pd.DataFrame:
    """Cumulative current-state vs target-state cost by year (one-time cost in year 1)."""
    current = recs.current_annual.sum()
    target = recs.target_annual.sum()
    one_time = recs.one_time_cost.sum()
    rows = []
    for y in range(0, years + 1):
        rows.append(dict(year=y, current_cumulative=current * y,
                         target_cumulative=(target * y + (one_time if y >= 1 else 0)),
                         net_benefit=current * y - (target * y + (one_time if y >= 1 else 0))))
    return pd.DataFrame(rows)


def tco_summary(recs: pd.DataFrame) -> dict:
    current = recs.current_annual.sum()
    target = recs.target_annual.sum()
    one_time = recs.one_time_cost.sum()
    saving = current - target
    return dict(current_annual=current, target_annual=target, annual_saving=saving, one_time=one_time,
                net_3yr=3 * saving - one_time, net_5yr=5 * saving - one_time,
                payback_months=round(one_time / (saving / 12), 1) if saving > 0 else None)


def savings_by_lever(recs: pd.DataFrame, licence_pos: pd.DataFrame) -> pd.DataFrame:
    """Split savings into validated / proposed / potential so assumptions are never presented as facts."""
    df = recs[recs.recommended_action != "Retain"].copy()
    df["lever"] = df.recommended_action.map(LEVER_OF)
    df.loc[df.target_platform.str.contains("Developer", na=False), "lever"] = "Non-prod to Developer edition"
    df["evidence_class"] = df.apply(lambda r: "Validated (approved)" if r.human_decision == "Approved" and r.readiness == "Ready"
                                    else "Potential (evidence gap)" if r.readiness == "Blocked" else "Proposed", axis=1)
    out = df.groupby(["lever", "evidence_class"]).agg(annual_saving=("annual_saving", "sum"),
                                                       licence_saving=("licence_saving", "sum"),
                                                       instances=("instance_id", "count")).reset_index()
    surplus = licence_pos.surplus_support_gbp.sum()
    if surplus:
        out = pd.concat([out, pd.DataFrame([dict(lever="Surplus entitlements (support)", evidence_class="Proposed",
                                                 annual_saving=surplus, licence_saving=surplus,
                                                 instances=int((licence_pos.surplus_support_gbp > 0).sum()))])],
                        ignore_index=True)
    return out


def licence_optimisation(recs: pd.DataFrame, licence_pos: pd.DataFrame, cost_records: pd.DataFrame) -> dict:
    """Conservative licence/support opportunity.

    Proposed  = Ready recommendations (excluding cloud moves, where licence cost shifts into
                compute) + support on surplus entitlements.
    Potential = Conditional / Blocked recommendations - only counted once conditions are cleared.
    """
    spend = licence_pos.annual_support_gbp.sum() + cost_records.loc[
        cost_records.cost_type.isin(["extended_security_updates", "sustaining_support_uplift"]), "annual_cost_gbp"].sum()
    licence_levers = recs[~recs.recommended_action.isin(["Retain", "Cloud Migrate"])]
    ready = licence_levers[licence_levers.readiness == "Ready"]
    pending = licence_levers[licence_levers.readiness != "Ready"]
    proposed = ready.licence_saving.clip(lower=0).sum() + licence_pos.surplus_support_gbp.sum()
    potential = pending.licence_saving.clip(lower=0).sum()
    return dict(licence_support_spend=spend, proposed=proposed, potential=potential,
                proposed_pct=round(100 * proposed / spend, 1) if spend else 0,
                potential_pct=round(100 * (proposed + potential) / spend, 1) if spend else 0)


def budget_scenario(recs: pd.DataFrame, risk: pd.DataFrame, cut_pct: float = 20.0) -> dict:
    """Re-prioritise the programme under a reduced one-time budget.

    Mandatory items (unsupported production / PCI risk remediation) are funded first;
    the remainder is ranked by 5-year net benefit per £ of one-time cost.
    """
    prog = recs[(recs.recommended_action != "Retain") & (recs.readiness != "Blocked")].merge(
        risk[["instance_id", "lifecycle_status", "risk_score"]], on="instance_id")
    baseline = prog.one_time_cost.sum()
    budget = baseline * (1 - cut_pct / 100)
    prog["mandatory"] = (prog.lifecycle_status == "Unsupported") & (prog.environment == "Production")
    prog["roi"] = prog.net_5yr / prog.one_time_cost.clip(lower=1)
    prog = prog.sort_values(["mandatory", "roi", "risk_score"], ascending=[False, False, False])
    spent, funded = 0.0, []
    for r in prog.itertuples():
        ok = spent + r.one_time_cost <= budget
        funded.append(ok)
        if ok:
            spent += r.one_time_cost
    prog["funded"] = funded
    f = prog[prog.funded]
    # Risk-driven items can have negative savings; measure retention on the positive savings pool only.
    base_saving = prog.annual_saving.clip(lower=0).sum()
    funded_saving = f.annual_saving.clip(lower=0).sum()
    return dict(baseline_budget=baseline, reduced_budget=budget, spent=spent, programme=prog,
                funded_count=int(prog.funded.sum()), deferred_count=int((~prog.funded).sum()),
                baseline_annual_saving=base_saving, funded_annual_saving=funded_saving,
                saving_retained_pct=round(100 * funded_saving / base_saving, 1) if base_saving else 0,
                deferred_risk_items=int((~prog.funded & prog.lifecycle_status.isin(["Unsupported", "Approaching EOS"])).sum()),
                mandatory_funded=int(f.mandatory.sum()), mandatory_total=int(prog.mandatory.sum()))


def migration_waves(recs: pd.DataFrame, risk: pd.DataFrame, groups: dict[str, str]) -> pd.DataFrame:
    df = recs.merge(risk[["instance_id", "lifecycle_status", "risk_score"]], on="instance_id")
    df["move_group"] = df.instance_id.map(groups).fillna("")

    def wave(r) -> str:
        if r.recommended_action == "Retain":
            return "No action"
        if r.readiness == "Blocked":
            return "Wave 3 - Evidence first"
        if r.recommended_action in ("Retire", "Consolidate") or "Developer" in str(r.target_platform) or (
                r.recommended_action == "Replatform" and r.environment != "Production"):
            return "Wave 0 - Quick wins (0-3 months)"
        if r.recommended_action == "Upgrade" or r.lifecycle_status == "Unsupported":
            return "Wave 1 - Risk remediation (3-9 months)"
        return "Wave 2 - Modernise (6-15 months)"

    df["wave"] = df.apply(wave, axis=1)
    # Databases sharing db-to-db interfaces move together: align to the latest wave in the group
    order = {"Wave 0 - Quick wins (0-3 months)": 0, "Wave 1 - Risk remediation (3-9 months)": 1,
             "Wave 2 - Modernise (6-15 months)": 2, "Wave 3 - Evidence first": 3}
    movers = df[df.recommended_action.isin(["Cloud Migrate", "Replatform"]) & (df.move_group != "")]
    for grp, members in movers.groupby("move_group"):
        latest = max(members.wave.map(order))
        label = [k for k, v in order.items() if v == latest][0]
        df.loc[members.index, "wave"] = label
    return df
