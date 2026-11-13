import pandas as pd
import pytest

from dboptima.reference import MIGRATION_OPTIONS


def test_planted_cases_match_expected_outcomes(analysis):
    exp = analysis.data["expected_outcomes"].merge(analysis.recs, on="instance_id")
    mismatches = exp[(exp.expected_action != exp.recommended_action) | (exp.expected_readiness != exp.readiness)]
    assert mismatches.empty, mismatches[["instance_id", "expected_action", "recommended_action", "expected_readiness", "readiness"]]


def test_never_ready_when_dependencies_or_recovery_unknown(analysis):
    recs = analysis.recs.merge(analysis.dep_profiles[["instance_id", "dependencies_known"]], on="instance_id") \
        .merge(analysis.data["recovery_requirements"][["instance_id", "rpo_minutes"]], on="instance_id")
    unknown = recs[recs.recommended_action.isin(MIGRATION_OPTIONS)
                   & (~recs.dependencies_known | (recs.rpo_minutes.isna() & (recs.recommended_action != "Retire")))]
    assert len(unknown) > 0
    assert (unknown.readiness == "Blocked").all()


def test_not_feasible_options_are_never_recommended(analysis):
    joined = analysis.recs.merge(analysis.options, left_on=["instance_id", "recommended_action"], right_on=["instance_id", "option"])
    assert (joined.status != "Not feasible").all()


def test_on_premises_only_residency_blocks_cloud(analysis):
    onprem = analysis.data["database_instances"].query("data_residency == 'On-Premises Only'").instance_id
    cloud = analysis.options[(analysis.options.option == "Cloud Migrate") & analysis.options.instance_id.isin(onprem)]
    assert len(cloud) > 0 and (cloud.status == "Not feasible").all()


def test_rac_targets_exadata_and_never_postgres(analysis):
    rac = analysis.data["database_instances"].query("cluster_type.str.startswith('RAC')", engine="python").instance_id
    opts = analysis.options[analysis.options.instance_id.isin(rac)]
    cloud = opts[opts.option == "Cloud Migrate"]
    assert cloud.target_platform.str.contains("Exadata").all()
    pg = opts[(opts.option == "Replatform") & opts.target_platform.str.contains("PostgreSQL")]
    assert (pg.status == "Not feasible").all()


def test_value_gate_keeps_change_below_retain_without_case(analysis):
    o = analysis.options
    retain = o[o.option == "Retain"].set_index("instance_id").score
    gated = o[o.drivers.str.contains("Value gate", na=False)]
    assert len(gated) > 0
    assert (gated.apply(lambda r: r.score < retain[r.instance_id], axis=1)).all()


def test_negative_business_case_only_when_fixing_lifecycle_risk(analysis):
    r = analysis.recs.merge(analysis.risk[["instance_id", "lifecycle_status"]], on="instance_id")
    neg = r[(r.recommended_action != "Retain") & (r.net_5yr < 0)]
    assert neg.lifecycle_status.isin(["Unsupported", "Approaching EOS"]).all()
    assert neg.rationale.str.startswith("Risk-driven").all()


def test_every_recommendation_is_traceable(analysis):
    assert analysis.kpis["traceability"]["actual"] == 100.0
    assert analysis.evidence.groupby("recommendation_id").size().min() >= 6


def test_discovery_outage_degrades_confidence_not_crash(analysis, analysis_oracle_down):
    base = analysis.recs[analysis.recs.db_engine == "Oracle"].confidence_pct.mean()
    down = analysis_oracle_down.recs[analysis_oracle_down.recs.db_engine == "Oracle"].confidence_pct.mean()
    assert down < base
    sql_base = analysis.recs[analysis.recs.db_engine == "SQL Server"].confidence_pct
    sql_down = analysis_oracle_down.recs[analysis_oracle_down.recs.db_engine == "SQL Server"].confidence_pct
    pd.testing.assert_series_equal(sql_base.reset_index(drop=True), sql_down.reset_index(drop=True))
    ora_changes = analysis_oracle_down.recs[(analysis_oracle_down.recs.db_engine == "Oracle")
                                            & (analysis_oracle_down.recs.recommended_action != "Retain")]
    assert not (ora_changes.readiness == "Ready").any()


@pytest.mark.parametrize("cut", [10, 20, 40])
def test_budget_scenario_respects_budget_and_funds_mandatory_first(analysis, cut):
    from dboptima.tco import budget_scenario

    b = budget_scenario(analysis.recs, analysis.risk, cut)
    assert b["spent"] <= b["reduced_budget"] + 1e-6
    assert 0 < b["saving_retained_pct"] <= 100
    prog = b["programme"]
    assert prog.mandatory.is_monotonic_decreasing  # mandatory risk remediation is prioritised first
    assert b["funded_count"] + b["deferred_count"] == len(prog)
