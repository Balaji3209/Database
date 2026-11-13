-- DB-OPTIMA AI application database (SQLite; portable to PostgreSQL).
-- Every evidence table keeps source reference, collection timestamp and evidence quality.

CREATE TABLE IF NOT EXISTS applications (
    application_id        TEXT PRIMARY KEY,
    application_name      TEXT NOT NULL,
    business_service_id   TEXT,
    business_service      TEXT,
    criticality_tier      TEXT,
    primary_engine        TEXT,
    certified_db_versions TEXT,
    sourcing              TEXT,
    business_owner        TEXT,
    data_label            TEXT
);

CREATE TABLE IF NOT EXISTS database_instances (
    instance_id                 TEXT PRIMARY KEY,
    data_label                  TEXT,
    db_engine                   TEXT NOT NULL,
    hostname                    TEXT,
    instance_name               TEXT,
    database_name               TEXT,
    major_version               TEXT,
    version_build               TEXT,
    patch_level                 TEXT,
    edition                     TEXT,
    environment                 TEXT,
    business_service            TEXT,
    application_id              TEXT REFERENCES applications(application_id),
    owner                       TEXT,
    location                    TEXT,
    server_type                 TEXT,
    os_platform                 TEXT,
    cpu_architecture            TEXT,
    cpu_sockets                 INTEGER,
    physical_cores              INTEGER,
    vcpus                       INTEGER,
    cluster_physical_cores      INTEGER,
    memory_gb                   REAL,
    storage_allocated_gb        REAL,
    db_size_gb                  REAL,
    cluster_type                TEXT,
    ha_dr_config                TEXT,
    backup_method               TEXT,
    character_set_or_collation  TEXT,
    code_objects                INTEGER,
    db_links_or_linked_servers  INTEGER,
    uses_java_or_aq             INTEGER,
    pdb_count                   INTEGER,
    uses_clr                    INTEGER,
    uses_filestream             INTEGER,
    uses_cross_db_queries       INTEGER,
    uses_sql_agent_jobs         INTEGER,
    uses_ssis                   INTEGER,
    data_classification         TEXT,
    data_residency              TEXT,
    dependency_evidence         TEXT,
    esu_or_sustaining_support   INTEGER,
    cmdb_ci_id                  TEXT,
    discovery_source_ref        TEXT,
    collected_at                TEXT
);

CREATE TABLE IF NOT EXISTS dependencies (
    dependency_id    TEXT PRIMARY KEY,
    source_type      TEXT,
    source_id        TEXT,
    target_type      TEXT,
    target_id        TEXT,
    dependency_type  TEXT,
    interface        TEXT,
    criticality      TEXT,
    status           TEXT,
    evidence_source  TEXT,
    confidence       TEXT,
    data_label       TEXT
);

CREATE TABLE IF NOT EXISTS feature_usage (
    instance_id       TEXT REFERENCES database_instances(instance_id),
    feature_name      TEXT,
    product_option    TEXT,
    licensable        INTEGER,
    detected_usages   INTEGER,
    currently_used    INTEGER,
    first_usage_date  TEXT,
    last_usage_date   TEXT,
    source            TEXT,
    evidence_quality  TEXT,
    collected_at      TEXT
);

CREATE TABLE IF NOT EXISTS license_entitlements (
    entitlement_id        TEXT PRIMARY KEY,
    vendor                TEXT,
    product               TEXT,
    metric                TEXT,
    quantity              INTEGER,
    unit_list_price_gbp   REAL,
    support_rate          REAL,
    annual_support_gbp    REAL,
    agreement_ref         TEXT,
    support_renewal_date  TEXT,
    source_document       TEXT,
    evidence_quality      TEXT,
    data_label            TEXT
);

CREATE TABLE IF NOT EXISTS workload_metrics (
    instance_id              TEXT REFERENCES database_instances(instance_id),
    window_days              INTEGER,
    cpu_avg_pct              REAL,
    cpu_p95_pct              REAL,
    memory_used_pct          REAL,
    iops_p95                 INTEGER,
    storage_growth_gb_month  REAL,
    peak_sessions            INTEGER,
    connections_90d          INTEGER,
    last_connection_date     TEXT,
    source                   TEXT,
    collected_at             TEXT,
    evidence_quality         TEXT
);

CREATE TABLE IF NOT EXISTS recovery_requirements (
    instance_id             TEXT REFERENCES database_instances(instance_id),
    criticality_tier        TEXT,
    rpo_minutes             REAL,
    rto_minutes             REAL,
    backup_frequency        TEXT,
    backup_retention_days   INTEGER,
    last_restore_test_date  TEXT,
    dr_site                 TEXT,
    source                  TEXT,
    validated_by            TEXT,
    evidence_quality        TEXT
);

CREATE TABLE IF NOT EXISTS cost_records (
    instance_id       TEXT REFERENCES database_instances(instance_id),
    cost_type         TEXT,
    annual_cost_gbp   REAL,
    source            TEXT,
    evidence_quality  TEXT,
    is_assumption     INTEGER,
    fiscal_year       TEXT,
    data_label        TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id   TEXT PRIMARY KEY,
    instance_id         TEXT REFERENCES database_instances(instance_id),
    recommended_action  TEXT,
    target_platform     TEXT,
    readiness           TEXT,
    score               REAL,
    runner_up           TEXT,
    current_annual      REAL,
    target_annual       REAL,
    annual_saving       REAL,
    licence_saving      REAL,
    one_time_cost       REAL,
    payback_months      REAL,
    net_5yr             REAL,
    confidence_pct      REAL,
    confidence          TEXT,
    rationale           TEXT,
    constraints         TEXT,
    conditions          TEXT,
    next_action         TEXT,
    assumptions         TEXT,
    human_decision      TEXT,
    approval_required   TEXT,
    generated_at        TEXT
);

CREATE TABLE IF NOT EXISTS recommendation_evidence (
    recommendation_id  TEXT REFERENCES recommendations(recommendation_id),
    instance_id        TEXT,
    evidence_type      TEXT,
    quality            TEXT,
    source             TEXT,
    fact               TEXT,
    collected_at       TEXT
);

CREATE TABLE IF NOT EXISTS decision_audit (
    audit_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id  TEXT,
    instance_id        TEXT,
    decision           TEXT CHECK (decision IN ('Approved', 'Rejected', 'Deferred', 'More evidence requested')),
    decided_action     TEXT,
    decided_by         TEXT NOT NULL,
    role               TEXT,
    comment            TEXT,
    decided_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_dep_target ON dependencies(target_id);
CREATE INDEX IF NOT EXISTS ix_feat_inst ON feature_usage(instance_id);
CREATE INDEX IF NOT EXISTS ix_audit_rec ON decision_audit(recommendation_id);
