import pandas as pd

from dboptima import reconciliation as rc
from dboptima.data_generator import oracle_processors
from dboptima.license_intel import edition_fit, sql_enterprise_features_in_use


def test_normalisation_of_cmdb_free_text():
    assert rc.normalize_engine("MS SQL") == "SQL Server"
    assert rc.normalize_environment("PRD") == "Production"
    assert rc.normalize_environment("UAT") == "Pre-Production"
    assert rc.normalize_edition("EE", "Oracle") == "Enterprise Edition"
    assert rc.normalize_edition("Enterprise Edition: Core-based Licensing (64-bit)", "SQL Server") == "Enterprise"
    assert rc.normalize_version("19.24.0.0.0", "Oracle") == "19c (19.x)"
    assert rc.normalize_version("12.2", "Oracle") == "12c R2 (12.2.0.1)"
    assert rc.normalize_version("12c", "Oracle").startswith("12c (ambiguous")
    assert rc.normalize_version("2014", "SQL Server") == "SQL Server 2014"
    assert rc.normalize_version("15.0.4400.1", "SQL Server") == "SQL Server 2019"
    assert rc.match_key("LONORA001P.CORP.DEMO.LOCAL", "PAYP1") == rc.match_key("lonora001p", "payp1")


def test_reconciliation_detects_injected_issues(analysis):
    s = analysis.recon["summary"]
    assert s["shadow"] == 2 and s["ghost"] == 2 and s["not_discovered"] == 2 and s["duplicates"] == 1
    assert s["conflicts_resolved"] >= 10
    assert s["reconciliation_rate"] >= 95


def test_discovery_outage_falls_back_to_stale_snapshot(analysis, analysis_oracle_down):
    down = analysis_oracle_down.recon
    assert down["summary"]["stale_snapshot"] == int((down["per_instance"].db_engine == "Oracle").sum() - 1)  # 1 Oracle never discovered
    assert down["summary"]["reconciliation_rate"] == analysis.recon["summary"]["reconciliation_rate"]
    assert analysis.recon["summary"]["stale_snapshot"] == 0


def _inst(**kw):
    base = dict(db_engine="Oracle", edition="Enterprise Edition", cpu_sockets=1, vcpus=16, physical_cores=8,
                cluster_physical_cores=8, cpu_architecture="x86_64", cluster_type="Single instance",
                ha_dr_config="None (backup/restore only)", memory_gb=64, major_version="19c (19.x)")
    base.update(kw)
    return base


EMPTY = pd.DataFrame(columns=["feature_name", "product_option", "currently_used"])


def test_oracle_core_factor_and_cluster_exposure():
    assert oracle_processors(_inst(physical_cores=16)) == 8
    assert oracle_processors(_inst(physical_cores=16, cpu_architecture="IBM POWER")) == 16
    assert oracle_processors(_inst(cluster_physical_cores=128), use_cluster=True) == 64


def test_se2_fit_respects_limits_and_options():
    assert edition_fit(_inst(), EMPTY)["candidate"]
    assert not edition_fit(_inst(cpu_sockets=4), EMPTY)["candidate"]
    assert not edition_fit(_inst(vcpus=32), EMPTY)["candidate"]
    assert not edition_fit(_inst(cluster_type="RAC (2-node)"), EMPTY)["candidate"]
    used = pd.DataFrame([dict(feature_name="Partitioning (user)", product_option="Partitioning", currently_used=True)])
    assert not edition_fit(_inst(), used)["candidate"]
    dg = edition_fit(_inst(ha_dr_config="Data Guard (physical standby, MaxAvailability)"), EMPTY)
    assert dg["candidate"] and dg["conditions"]


def test_sql_feature_parity_after_2016_sp1():
    feats = pd.DataFrame([dict(feature_name="Table Partitioning", currently_used=True),
                          dict(feature_name="Online Index Rebuild", currently_used=True)])
    assert sql_enterprise_features_in_use(feats, "SQL Server 2014") == ["Table Partitioning", "Online Index Rebuild"]
    assert sql_enterprise_features_in_use(feats, "SQL Server 2019") == ["Online Index Rebuild"]


def test_licence_position_never_claims_compliance(analysis):
    statuses = set(analysis.licence_position.status)
    assert all("compliant" not in s.lower() for s in statuses)
    assert any("validate" in s for s in statuses)
