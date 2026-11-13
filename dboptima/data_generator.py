"""Synthetic data generator for the DB-OPTIMA AI pilot.

Produces 150 database instances (75 Oracle, 75 SQL Server) across two business services,
plus every evidence source the advisor reconciles. All records are clearly flagged as
SYNTHETIC DEMO DATA. Generation is deterministic (seeded) so results are reproducible.

Deliberate data-quality issues are injected so the platform can demonstrate detection:
missing owners/applications, CMDB-vs-discovery conflicts, shadow and ghost records,
duplicate CIs, unknown dependencies, unknown RPO/RTO and stale/false-positive feature usage.
A set of "planted" instances has known expected outcomes for testing the decision engine.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import reference as ref
from .config import ASSESSMENT_DATE, DATA_DIR, get_logger

log = get_logger("data_generator")

SEED = 42
DOMAIN = "corp.demo.local"

BUSINESS_SERVICES = {"BS-PAY": "Payments & Checkout", "BS-SCM": "Supply Chain & Inventory"}

# application_id: (name, service, tier, primary_engine, code, certified versions, vendor/in-house)
APPLICATIONS = [
    ("APP-PGW", "Card Payment Gateway", "BS-PAY", 0, "Oracle", "PGW", "Oracle 19c;Oracle 23ai", "Vendor package"),
    ("APP-OMS", "Order Management", "BS-PAY", 1, "Oracle", "OMS", "Oracle 19c", "Vendor package"),
    ("APP-PRC", "Payment Reconciliation", "BS-PAY", 1, "Oracle", "PRC", "Oracle 19c;Oracle 23ai", "In-house"),
    ("APP-GFT", "Gift Card Platform", "BS-PAY", 2, "Oracle", "GFT", "Unknown", "Vendor package"),
    ("APP-WMS", "Warehouse Management", "BS-SCM", 1, "Oracle", "WMS", "Oracle 19c", "Vendor package"),
    ("APP-SRP", "Stock Replenishment", "BS-SCM", 1, "Oracle", "SRP", "Oracle 19c;Oracle 23ai", "In-house"),
    ("APP-SUP", "Supplier Portal", "BS-SCM", 3, "Oracle", "SUP", "Oracle 19c;PostgreSQL 16", "In-house"),
    ("APP-DFC", "Demand Forecasting", "BS-SCM", 2, "Oracle", "DFC", "Oracle 19c", "In-house"),
    ("APP-LOY", "Customer Loyalty", "BS-PAY", 2, "SQL Server", "LOY", "SQL Server 2019;SQL Server 2022;Azure SQL", "In-house"),
    ("APP-RFD", "Refunds & Returns", "BS-PAY", 1, "SQL Server", "RFD", "SQL Server 2022;Azure SQL", "In-house"),
    ("APP-FRD", "Fraud Screening", "BS-PAY", 0, "SQL Server", "FRD", "SQL Server 2019;SQL Server 2022", "Vendor package"),
    ("APP-POS", "Store POS Back-office", "BS-PAY", 1, "SQL Server", "POS", "SQL Server 2019", "Vendor package"),
    ("APP-TMS", "Transport Management", "BS-SCM", 2, "SQL Server", "TMS", "SQL Server 2022;Azure SQL", "Vendor package"),
    ("APP-PIM", "Product Information Mgmt", "BS-SCM", 2, "SQL Server", "PIM", "SQL Server 2022;Azure SQL", "In-house"),
    ("APP-INV", "Inventory Visibility", "BS-SCM", 1, "SQL Server", "INV", "SQL Server 2019;SQL Server 2022;Azure SQL", "In-house"),
    ("APP-DPL", "Distribution Planning", "BS-SCM", 3, "SQL Server", "DPL", "Unknown", "In-house"),
]

FIRST = ["Aarav", "Priya", "James", "Sophie", "Rahul", "Emma", "Oliver", "Ananya", "Liam", "Grace", "Vikram", "Chloe"]
LAST = ["Sharma", "Patel", "Smith", "Jones", "Iyer", "Taylor", "Brown", "Nair", "Wilson", "Khan", "Evans", "Reddy"]

ENV_CODE = {"Production": ("p", "P"), "Pre-Production": ("u", "U"), "Test": ("t", "T"), "Development": ("d", "D")}

ORACLE_ENV_MIX = ["Production"] * 30 + ["Pre-Production"] * 12 + ["Test"] * 15 + ["Development"] * 18
SQL_ENV_MIX = ["Production"] * 28 + ["Pre-Production"] * 12 + ["Test"] * 17 + ["Development"] * 18

# --------------------------------------------------------------------------------------
# Planted scenarios with known expected outcomes (used by tests and the jury demo)
# --------------------------------------------------------------------------------------
PLANTED: dict[str, dict] = {
    "ORA-0001": dict(environment="Production", app="APP-PRC", major_version="11g R2 (11.2.0.4)", edition="Enterprise Edition",
                     server_type="Physical", os_platform="Oracle Linux 7.9", physical_cores=16, cpu_sockets=2, memory_gb=256,
                     ha_dr_config="Data Guard (physical standby, MaxAvailability)", plsql_objects=2500, db_links=2,
                     data_classification="Confidential (PII)", data_residency="UK", dependency_evidence="APM + DB catalogue",
                     cpu_p95=62, features=["Partitioning (user)", "Automatic Workload Repository"],
                     _expected=("Upgrade", "Ready", "Unsupported Oracle 11.2.0.4 with heavy PL/SQL and options in use - in-place upgrade to 19c is the lowest-risk fix.")),
    "ORA-0002": dict(environment="Production", app="APP-DFC", major_version="19c (19.x)", edition="Enterprise Edition",
                     server_type="Physical", os_platform="Oracle Linux 8.9", physical_cores=8, cpu_sockets=1, memory_gb=128,
                     ha_dr_config="None (backup/restore only)", plsql_objects=1400, db_links=1, data_classification="Internal",
                     data_residency="UK", dependency_evidence="APM + DB catalogue", cpu_p95=45, features=[],
                     _expected=("Replatform", "Ready", "Enterprise Edition with zero EE options in use and within SE2 limits - edition downgrade releases EE support.")),
    "ORA-0003": dict(environment="Test", app="APP-GFT", major_version="12c R1 (12.1.0.2)", edition="Enterprise Edition",
                     server_type="VMware VM", os_platform="RHEL 7.9", physical_cores=4, cpu_sockets=1, memory_gb=32,
                     ha_dr_config="None (backup/restore only)", plsql_objects=600, db_links=0, data_classification="Internal",
                     data_residency="UK", dependency_evidence="APM + DB catalogue", cpu_p95=2, idle_days=210, features=[],
                     _expected=("Retire", "Ready", "No connections for 210 days and no active dependants - retire and harvest licences.")),
    "ORA-0004": dict(environment="Production", app="APP-SRP", major_version="19c (19.x)", edition="Enterprise Edition",
                     server_type="Physical", os_platform="Oracle Linux 8.9", physical_cores=8, cpu_sockets=1, memory_gb=128,
                     ha_dr_config="None (backup/restore only)", plsql_objects=900, db_links=0, data_classification="Internal",
                     data_residency="UK", dependency_evidence="None", cpu_p95=40, features=[],
                     _expected=("Replatform", "Blocked", "Edition downgrade is attractive but dependencies are unknown - hard constraint blocks readiness.")),
    "ORA-0005": dict(environment="Production", app="APP-WMS", major_version="12c R1 (12.1.0.2)", edition="Enterprise Edition",
                     server_type="Physical", os_platform="Oracle Linux 7.9", physical_cores=16, cpu_sockets=2, memory_gb=256,
                     ha_dr_config="Data Guard (physical standby, MaxAvailability)", plsql_objects=3200, db_links=3,
                     data_classification="Internal", data_residency="UK", dependency_evidence="APM + DB catalogue",
                     cpu_p95=58, recovery_unknown=True, features=["Partitioning (user)", "Automatic Workload Repository", "SQL Tuning Advisor"],
                     _expected=("Upgrade", "Conditional", "Unsupported 12.1 - upgrade needed but RPO/RTO unknown, so downtime window cannot be validated.")),
    "ORA-0006": dict(environment="Production", app="APP-PGW", major_version="12c R2 (12.2.0.1)", edition="Enterprise Edition",
                     server_type="Physical", os_platform="Oracle Linux 7.9", physical_cores=24, cpu_sockets=2, memory_gb=512,
                     cluster_type="RAC (2-node)", ha_dr_config="RAC 2-node + Active Data Guard", plsql_objects=5800, db_links=4,
                     data_classification="Restricted (PCI-DSS)", data_residency="UK", dependency_evidence="APM + DB catalogue",
                     cpu_p95=72, uses_java_or_aq=True,
                     features=["Real Application Clusters (RAC)", "Active Data Guard - Real-Time Query on Physical Standby",
                               "Partitioning (user)", "Automatic Workload Repository", "SQL Tuning Advisor", "Transparent Data Encryption"],
                     _expected=("Upgrade", "Ready", "Tier-0 RAC/ADG payment DB on unsupported 12.2 - RAC not supported on Azure VMs; upgrade to 19c first.")),
    "ORA-0007": dict(environment="Production", app="APP-SUP", major_version="19c (19.x)", edition="Standard Edition 2",
                     server_type="VMware VM", os_platform="Oracle Linux 8.9", physical_cores=4, cpu_sockets=1, memory_gb=32,
                     ha_dr_config="None (backup/restore only)", plsql_objects=150, db_links=0, character_set="AL32UTF8",
                     data_classification="Internal", data_residency="UK", dependency_evidence="APM + DB catalogue", cpu_p95=35,
                     features=[], _expected=("Replatform", "Conditional", "Small SE2 database with low PL/SQL complexity - candidate for Azure PostgreSQL after code-conversion assessment.")),
    "MSS-0001": dict(environment="Production", app="APP-LOY", major_version="SQL Server 2014", edition="Enterprise",
                     server_type="VMware VM", os_platform="Windows Server 2012 R2", physical_cores=8, cpu_sockets=1, memory_gb=64,
                     ha_dr_config="Log Shipping", tsql_objects=420, linked_servers=0, uses_cross_db_queries=True,
                     uses_sql_agent_jobs=True, uses_filestream=False, uses_clr=False,
                     data_classification="Confidential (PII)", data_residency="UK", dependency_evidence="APM + DB catalogue",
                     cpu_p95=22, features=[],
                     _expected=("Cloud Migrate", "Ready", "SQL 2014 paying ESU - Azure SQL Managed Instance is evergreen, removes ESU and right-sizes compute.")),
    "MSS-0002": dict(environment="Production", app="APP-POS", major_version="SQL Server 2019", edition="Enterprise",
                     server_type="Physical", os_platform="Windows Server 2019", physical_cores=16, cpu_sockets=2, memory_gb=96,
                     ha_dr_config="Failover Cluster Instance", tsql_objects=900, linked_servers=1, uses_filestream=True,
                     data_classification="Internal", data_residency="UK", dependency_evidence="APM + DB catalogue", cpu_p95=38,
                     features=[], _expected=("Replatform", "Ready", "Enterprise edition with no Enterprise-only features, 16 cores / 96 GB within Standard limits.")),
    "MSS-0007": dict(environment="Production", app="APP-FRD", major_version="SQL Server 2014", edition="Enterprise",
                     server_type="Physical", os_platform="Windows Server 2012 R2", physical_cores=16, cpu_sockets=2, memory_gb=256,
                     ha_dr_config="Always On AG (sync, readable secondary)", tsql_objects=1600, linked_servers=2,
                     data_classification="Restricted (PCI-DSS)", data_residency="On-Premises Only",
                     dependency_evidence="APM + DB catalogue", cpu_p95=66,
                     features=["Always On AG - readable secondary", "Online Index Rebuild"],
                     _expected=("Upgrade", "Ready", "SQL 2014 with ESU but data residency is On-Premises Only - cloud is a hard-constraint fail; upgrade in place.")),
    "MSS-0008": dict(environment="Production", app="APP-DPL", major_version="SQL Server 2016", edition="Standard",
                     server_type="VMware VM", os_platform="Windows Server 2016", physical_cores=4, cpu_sockets=1, memory_gb=32,
                     ha_dr_config="None (backup/restore only)", tsql_objects=200, data_classification="Internal",
                     data_residency="UK", dependency_evidence="APM + DB catalogue", cpu_p95=1, idle_days=150, features=[],
                     _expected=("Retire", "Conditional", "Idle production DB for 150 days - retire, but production retirement needs owner sign-off and retention check.")),
}
for _i in range(3, 7):  # consolidation group of four low-utilisation test instances
    PLANTED[f"MSS-000{_i}"] = dict(
        environment="Test", app="APP-INV", major_version="SQL Server 2019", edition="Standard", server_type="VMware VM",
        os_platform="Windows Server 2019", physical_cores=4, cpu_sockets=1, memory_gb=32,
        ha_dr_config="None (backup/restore only)", tsql_objects=300, linked_servers=0, data_classification="Internal",
        data_residency="UK", dependency_evidence="APM + DB catalogue", cpu_p95=8 + _i, mem_used_pct=30, features=[],
        _expected=("Consolidate", "Ready", "Four Standard test instances for the same service under 15% CPU p95 - consolidate onto one host."))

# Data-quality gaps injected (instance ids chosen outside planted range)
PLANTED_DB_SIZE_GB = {"ORA-0001": 1800, "ORA-0002": 600, "ORA-0003": 120, "ORA-0004": 650, "ORA-0005": 2400,
                      "ORA-0006": 3800, "ORA-0007": 90, "MSS-0001": 350, "MSS-0002": 900, "MSS-0003": 60, "MSS-0004": 60,
                      "MSS-0005": 60, "MSS-0006": 60, "MSS-0007": 2200, "MSS-0008": 150}
GAPS = {
    "dependency_unknown": ["ORA-0012", "ORA-0019", "ORA-0027", "ORA-0041", "ORA-0058",
                           "MSS-0015", "MSS-0023", "MSS-0036", "MSS-0049", "MSS-0063"],
    "recovery_unknown": ["ORA-0014", "ORA-0033", "ORA-0047", "ORA-0066", "MSS-0018", "MSS-0029", "MSS-0052", "MSS-0068"],
    "owner_missing": ["ORA-0055", "MSS-0044"],
    "app_missing": ["MSS-0057"],
    "shadow_not_in_cmdb": ["ORA-0071", "MSS-0072"],
    "not_discovered": ["ORA-0074", "MSS-0074"],
    "edition_conflict": ["ORA-0021", "ORA-0034", "ORA-0062", "MSS-0026", "MSS-0039", "MSS-0061"],
    "version_conflict": ["ORA-0016", "ORA-0045", "MSS-0013", "MSS-0031", "MSS-0055"],
    "duplicate_ci": ["MSS-0060"],
    "se2_option_misuse": ["ORA-0043", "ORA-0068"],
}


class _Gen:
    def __init__(self, seed: int = SEED):
        self.rng = random.Random(seed)
        self.apps = {a[0]: a for a in APPLICATIONS}

    # ---------------------------------------------------------------- helpers
    def pick(self, weighted: dict):
        return self.rng.choices(list(weighted), weights=list(weighted.values()), k=1)[0]

    def person(self) -> str:
        return f"{self.rng.choice(FIRST).lower()}.{self.rng.choice(LAST).lower()}@contoso-demo.example"

    def days_ago(self, lo: int, hi: int) -> date:
        return ASSESSMENT_DATE - timedelta(days=self.rng.randint(lo, hi))

    # ---------------------------------------------------------------- instances
    def instances(self) -> list[dict]:
        rows = []
        for engine, prefix, env_mix in (("Oracle", "ORA", ORACLE_ENV_MIX), ("SQL Server", "MSS", SQL_ENV_MIX)):
            envs = env_mix[:]
            self.rng.shuffle(envs)
            engine_apps = [a for a in APPLICATIONS if a[4] == engine]
            for i in range(1, 76):
                iid = f"{prefix}-{i:04d}"
                plant = PLANTED.get(iid, {})
                env = plant.get("environment", envs[i - 1])
                app = self.apps[plant["app"]] if "app" in plant else engine_apps[(i - 1) % len(engine_apps)]
                rows.append(self._instance(iid, engine, i, env, app, plant))
        return rows

    def _instance(self, iid, engine, n, env, app, plant) -> dict:
        r = self.rng
        prod = env == "Production"
        app_id, app_name, svc, tier, _, code, _, _ = app
        site = self.pick({"lon": 50, "mcr": 35, "azu": 15})
        if engine == "Oracle":
            major = self.pick({"19c (19.x)": 46, "12c R2 (12.2.0.1)": 11, "12c R1 (12.1.0.2)": 10, "11g R2 (11.2.0.4)": 11,
                               "18c (18.x)": 4, "21c (21.x)": 10 if not prod else 4, "23ai (23.x)": 6 if not prod else 2})
            edition = self.pick({"Enterprise Edition": 85, "Standard Edition 2": 15} if prod else
                                {"Enterprise Edition": 62, "Standard Edition 2": 38})
            server_type = "Azure VM" if site == "azu" else self.pick({"Physical": 45, "VMware VM": 42, "IBM POWER LPAR": 13})
        else:
            major = self.pick({"SQL Server 2022": 18, "SQL Server 2019": 34, "SQL Server 2017": 15, "SQL Server 2016": 15,
                               "SQL Server 2014": 11, "SQL Server 2012": 7})
            edition = self.pick({"Enterprise": 45, "Standard": 55} if prod else
                                {"Developer": 52, "Standard": 32, "Enterprise": 16})
            server_type = "Azure VM" if site == "azu" else self.pick({"Physical": 25, "VMware VM": 75})
        major = plant.get("major_version", major)
        edition = plant.get("edition", edition)
        server_type = plant.get("server_type", server_type)
        if server_type != "Azure VM" and site == "azu":
            site = "lon"
        if server_type == "Azure VM":
            site = "azu"

        cores = plant.get("physical_cores", r.choice([8, 12, 16, 24, 32] if prod else [2, 4, 4, 8]))
        if edition == "Standard Edition 2":
            cores = min(cores, 8)
        sockets = plant.get("cpu_sockets", 2 if cores >= 16 else 1)
        memory = plant.get("memory_gb", r.choice([64, 128, 256, 384, 512] if prod else [16, 32, 64]))
        if edition == "Standard Edition 2":
            sockets = min(sockets, 2)
        vcpus = cores * 2 if server_type in ("Physical", "IBM POWER LPAR") else cores

        if engine == "Oracle":
            os_platform = "AIX 7.2" if server_type == "IBM POWER LPAR" and r.random() < 0.5 else (
                "AIX 7.3" if server_type == "IBM POWER LPAR" else
                ("Oracle Linux 7.9" if major in ("11g R2 (11.2.0.4)", "12c R1 (12.1.0.2)") else r.choice(["Oracle Linux 8.9", "RHEL 8.8", "RHEL 7.9"])))
            arch = "IBM POWER" if server_type == "IBM POWER LPAR" else "x86_64"
            ha = self.pick({"Data Guard (physical standby, MaxAvailability)": 45, "Active Data Guard (real-time query)": 15,
                            "RAC 2-node + Data Guard": 15, "None (backup/restore only)": 25} if prod else
                           {"None (backup/restore only)": 90, "Data Guard (physical standby, MaxAvailability)": 10})
            if edition == "Standard Edition 2" and ha != "None (backup/restore only)":
                ha = "Dbvisit Standby (SE2 manual standby)"
            cluster = "RAC (2-node)" if ha.startswith("RAC") else "Single instance"
            backup = r.choice(["RMAN incremental -> Commvault", "RMAN -> ZDLRA", "RMAN -> NFS (NetApp)"])
            charset = self.pick({"AL32UTF8": 70, "WE8MSWIN1252": 20, "WE8ISO8859P1": 10})
            objects = r.randint(300, 6000) if prod else r.randint(80, 3500)
            links = r.choice([0, 0, 1, 2, 3, 5])
            java_aq = r.random() < 0.15
            pdbs = r.choice([1, 1, 2, 3, 4, 6]) if major.split(" ")[0] in ("19c", "21c", "23ai") else 0
            sql_flags = dict(uses_clr=False, uses_filestream=False, uses_cross_db_queries=False, uses_sql_agent_jobs=False, uses_ssis=False)
        else:
            os_platform = "Windows Server 2012 R2" if major in ("SQL Server 2012", "SQL Server 2014") else (
                "Windows Server 2016" if major in ("SQL Server 2016", "SQL Server 2017") else r.choice(["Windows Server 2019", "Windows Server 2022"]))
            arch = "x86_64"
            ha = self.pick({"Always On AG (sync, readable secondary)": 25, "Always On AG (sync, non-readable)": 20,
                            "Failover Cluster Instance": 20, "Log Shipping": 15, "None (backup/restore only)": 20} if prod else
                           {"None (backup/restore only)": 92, "Log Shipping": 8})
            if edition != "Enterprise" and "readable" in ha and "non-readable" not in ha:
                ha = "Basic Availability Group (2 replicas)"
            cluster = "Failover cluster" if ha == "Failover Cluster Instance" else "Standalone"
            backup = r.choice(["Native backup to URL (Azure Blob)", "Commvault SQL agent", "Ola Hallengren -> NAS"])
            charset = r.choice(["Latin1_General_CI_AS", "SQL_Latin1_General_CP1_CI_AS"])
            objects = r.randint(150, 3000) if prod else r.randint(50, 1800)
            links = r.choice([0, 0, 1, 2, 3])
            java_aq = False
            pdbs = 0
            sql_flags = dict(uses_clr=r.random() < 0.15, uses_filestream=r.random() < 0.08,
                             uses_cross_db_queries=r.random() < 0.30, uses_sql_agent_jobs=r.random() < 0.8,
                             uses_ssis=r.random() < 0.2)
        os_platform = plant.get("os_platform", os_platform)
        ha = plant.get("ha_dr_config", ha)
        if engine == "Oracle":
            derived_cluster = "RAC (2-node)" if ha.startswith("RAC") else "Single instance"
        else:
            derived_cluster = "Failover cluster" if ha == "Failover Cluster Instance" else "Standalone"
        cluster = plant.get("cluster_type", derived_cluster)
        objects = plant.get("plsql_objects", plant.get("tsql_objects", objects))
        links = plant.get("db_links", plant.get("linked_servers", links))
        java_aq = plant.get("uses_java_or_aq", java_aq if "uses_java_or_aq" not in plant else plant["uses_java_or_aq"])
        if iid in PLANTED and "uses_java_or_aq" not in plant:
            java_aq = False
        charset = plant.get("character_set", charset)
        for k in list(sql_flags):
            if k in plant:
                sql_flags[k] = plant[k]
            elif iid in PLANTED:
                sql_flags[k] = sql_flags[k] and k in ("uses_sql_agent_jobs",)
        if iid in PLANTED and engine == "Oracle":
            pdbs = 1 if pdbs else 0

        db_size = PLANTED_DB_SIZE_GB.get(iid, round(r.uniform(80, 4500) if prod else r.uniform(10, 900), 1))
        storage = round(db_size * (1.6 if iid in PLANTED else r.uniform(1.4, 2.2)), 0)

        if svc == "BS-PAY" and tier <= 1 and prod:
            classification = "Restricted (PCI-DSS)" if app_id in ("APP-PGW", "APP-FRD") else "Confidential (PII)"
        elif svc == "BS-PAY":
            classification = "Confidential (PII)" if prod else "Confidential (masked copy)"
        else:
            classification = "Internal"
        residency = self.pick({"UK": 75, "EU": 8, "Any": 12, "On-Premises Only": 5})
        classification = plant.get("data_classification", classification)
        residency = plant.get("data_residency", residency)

        unsupported = ref.LIFECYCLE[engine][major]["extended_end"] < ASSESSMENT_DATE
        eng_code = "ora" if engine == "Oracle" else "sql"
        env_l, env_u = ENV_CODE[env]
        hostname = f"{site}{eng_code}{n:03d}{env_l}"
        if engine == "Oracle":
            instance_name = f"{code}{env_u}{(n % 3) + 1}"
            database_name = f"{code}{env_u}_PDB1" if pdbs else f"{code}{env_u}"
        else:
            instance_name = "MSSQLSERVER" if r.random() < 0.4 else f"SQL{code}{env_u}"
            database_name = f"{app_name.replace(' ', '').replace('&', 'And')}_{env_u}"

        dep_evidence = plant.get("dependency_evidence",
                                 "None" if iid in GAPS["dependency_unknown"] else self.pick({"APM + DB catalogue": 70, "CMDB relationship only": 30}))
        owner = "" if iid in GAPS["owner_missing"] + GAPS["shadow_not_in_cmdb"] else self.person()
        application_id = "" if iid in GAPS["app_missing"] + GAPS["shadow_not_in_cmdb"] else app_id
        business_service = "" if iid in GAPS["shadow_not_in_cmdb"] else svc
        cmdb_ci = "" if iid in GAPS["shadow_not_in_cmdb"] else f"CI{10000 + n + (0 if engine == 'Oracle' else 500)}"
        disc_ref = "" if iid in GAPS["not_discovered"] else (
            f"OEM13.5:{hostname}:{instance_name}" if engine == "Oracle" else f"dbatools-inventory:{hostname}\\{instance_name}")

        return dict(
            instance_id=iid, data_label="SYNTHETIC-DEMO", db_engine=engine, hostname=hostname, instance_name=instance_name,
            database_name=database_name, major_version=major, version_build=ref.VERSION_BUILDS[major],
            patch_level=(f"RU {ref.VERSION_BUILDS[major][:5]}" if engine == "Oracle" else f"CU{r.randint(10, 32)}"),
            edition=edition, environment=env, business_service=business_service, application_id=application_id,
            owner=owner, location={"lon": "DC-London", "mcr": "DC-Manchester", "azu": "Azure UK South (IaaS)"}[site],
            server_type=server_type, os_platform=os_platform, cpu_architecture=arch, cpu_sockets=sockets,
            physical_cores=cores, vcpus=vcpus, cluster_physical_cores=(r.choice([96, 128, 192]) if server_type == "VMware VM" else cores),
            memory_gb=memory, storage_allocated_gb=storage, db_size_gb=db_size, cluster_type=cluster, ha_dr_config=ha,
            backup_method=backup, character_set_or_collation=charset, code_objects=objects, db_links_or_linked_servers=links,
            uses_java_or_aq=java_aq, pdb_count=pdbs, **sql_flags,
            data_classification=classification, data_residency=residency, dependency_evidence=dep_evidence,
            esu_or_sustaining_support=bool(unsupported and (prod or env == "Pre-Production")),
            cmdb_ci_id=cmdb_ci, discovery_source_ref=disc_ref,
            collected_at=(self.days_ago(1, 12).isoformat() if disc_ref else ""),
        )

    # ---------------------------------------------------------------- evidence sources
    def workload(self, inst: pd.DataFrame) -> list[dict]:
        out = []
        for row in inst.itertuples():
            r = self.rng
            plant = PLANTED.get(row.instance_id, {})
            prod = row.environment == "Production"
            p95 = plant.get("cpu_p95", round(r.uniform(28, 88) if prod else r.uniform(3, 42), 1))
            idle = plant.get("idle_days")
            if idle is None and not plant and not prod and r.random() < 0.07:
                idle = r.randint(95, 400)
            conns = 0 if idle else (r.randint(20000, 2_000_000) if prod else r.randint(80, 60000))
            last_conn = ASSESSMENT_DATE - timedelta(days=idle if idle else r.randint(0, 2))
            out.append(dict(
                instance_id=row.instance_id, window_days=30, cpu_avg_pct=round(p95 * r.uniform(0.42, 0.6), 1), cpu_p95_pct=p95,
                memory_used_pct=plant.get("mem_used_pct", round(r.uniform(45, 92) if prod else r.uniform(15, 60), 1)),
                iops_p95=int(r.uniform(1500, 45000) if prod else r.uniform(50, 4000)),
                storage_growth_gb_month=round(row.db_size_gb * r.uniform(0.005, 0.03), 1),
                peak_sessions=(r.randint(150, 2500) if prod else r.randint(3, 120)) if not idle else 0,
                connections_90d=conns, last_connection_date=last_conn.isoformat(),
                source=("AWR / OEM metric extract" if row.db_engine == "Oracle" else "Query Store + perfmon (DMV collector)"),
                collected_at=row.collected_at or "", evidence_quality=("High" if row.discovery_source_ref else "Low"),
            ))
        return out

    def feature_usage(self, inst: pd.DataFrame) -> list[dict]:
        out = []
        for row in inst.itertuples():
            if not row.discovery_source_ref:
                continue
            r = self.rng
            plant = PLANTED.get(row.instance_id)
            if row.db_engine == "Oracle":
                used: list[tuple[str, bool]] = []
                if plant is not None:
                    used = [(f, True) for f in plant.get("features", [])]
                elif row.edition == "Enterprise Edition":
                    prob = {"Partitioning (user)": 0.35, "OLTP Table Compression": 0.15, "Automatic Workload Repository": 0.55,
                            "SQL Tuning Advisor": 0.25, "In-Memory Column Store": 0.05, "Database Replay: Workload Capture": 0.05,
                            "Oracle Database Vault": 0.03}
                    for f, p in prob.items():
                        if r.random() < p:
                            used.append((f, r.random() > 0.12))
                    if "PCI" in row.data_classification or r.random() < 0.12:
                        used.append(("Transparent Data Encryption", True))
                    if row.cluster_type.startswith("RAC"):
                        used.append(("Real Application Clusters (RAC)", True))
                    if "Active Data Guard" in row.ha_dr_config:
                        used.append(("Active Data Guard - Real-Time Query on Physical Standby", True))
                    if row.pdb_count > 3:
                        used.append(("Oracle Multitenant (>3 user PDBs)", True))
                elif row.instance_id in GAPS["se2_option_misuse"]:
                    used.append(("Automatic Workload Repository", True))
                for f, current in used:
                    first = self.days_ago(400, 2200)
                    last = self.days_ago(0, 6) if current else self.days_ago(380, 900)
                    out.append(dict(instance_id=row.instance_id, feature_name=f, product_option=ref.ORACLE_OPTIONS[f]["option"],
                                    licensable=True, detected_usages=r.randint(3, 900), currently_used=current,
                                    first_usage_date=first.isoformat(), last_usage_date=max(first, last).isoformat(),
                                    source="DBA_FEATURE_USAGE_STATISTICS (options_packs_usage_statistics.sql)",
                                    evidence_quality="Medium" if f == "Automatic Workload Repository" else "High",
                                    collected_at=row.collected_at))
            else:
                feats: list[str] = []
                if plant is not None:
                    feats = plant.get("features", [])
                elif row.edition == "Enterprise":
                    if "readable secondary" in row.ha_dr_config:
                        feats.append("Always On AG - readable secondary")
                    for f, p in {"Online Index Rebuild": 0.4, "Resource Governor": 0.1, "Peer-to-Peer Replication": 0.03,
                                 "Table Partitioning": 0.3, "Data Compression": 0.3, "Transparent Data Encryption": 0.15}.items():
                        if r.random() < p:
                            feats.append(f)
                for f in feats:
                    out.append(dict(instance_id=row.instance_id, feature_name=f, product_option=f, licensable=True,
                                    detected_usages=r.randint(5, 500), currently_used=True,
                                    first_usage_date=self.days_ago(300, 1800).isoformat(), last_usage_date=self.days_ago(0, 5).isoformat(),
                                    source="sys.dm_db_persisted_sku_features + server configuration",
                                    evidence_quality="High", collected_at=row.collected_at))
        return out

    def recovery(self, inst: pd.DataFrame) -> list[dict]:
        tier_rpo_rto = {0: (0, 15), 1: (5, 60), 2: (60, 240), 3: (1440, 2880)}
        out = []
        for row in inst.itertuples():
            app = self.apps.get(row.application_id) or self.apps[[a for a in self.apps if self.apps[a][4] == row.db_engine][0]]
            tier = app[3] if row.environment == "Production" else 3
            unknown = row.instance_id in GAPS["recovery_unknown"] or PLANTED.get(row.instance_id, {}).get("recovery_unknown")
            rpo, rto = tier_rpo_rto[tier]
            restore_test = self.days_ago(20, 700)
            out.append(dict(
                instance_id=row.instance_id, criticality_tier=f"Tier {tier}",
                rpo_minutes=None if unknown else rpo, rto_minutes=None if unknown else rto,
                backup_frequency=("Full weekly + incremental daily + archive log 15 min" if row.db_engine == "Oracle"
                                  else "Full weekly + diff daily + log 15 min"),
                backup_retention_days=self.rng.choice([14, 30, 35, 90]),
                last_restore_test_date=restore_test.isoformat(),
                dr_site=("DC-Manchester" if "London" in row.location else "DC-London") if row.ha_dr_config.split(" ")[0] not in ("None",) else "",
                source="Not recorded" if unknown else "Business Impact Analysis register FY26",
                validated_by="" if unknown else self.person(),
                evidence_quality="Missing" if unknown else "High",
            ))
        return out

    def dependencies(self, inst: pd.DataFrame, workload: pd.DataFrame) -> list[dict]:
        out = []
        idle = set(workload.loc[workload.connections_90d == 0, "instance_id"])
        known = inst[inst.dependency_evidence != "None"]
        dep_id = 1

        def add(src_type, src, tgt, dtype, interface, crit, evidence, conf, status="Active"):
            nonlocal dep_id
            out.append(dict(dependency_id=f"DEP-{dep_id:04d}", source_type=src_type, source_id=src, target_type="database",
                            target_id=tgt, dependency_type=dtype, interface=interface, criticality=crit, status=status,
                            evidence_source=evidence, confidence=conf, data_label="SYNTHETIC-DEMO"))
            dep_id += 1

        for row in known.itertuples():
            app_id = row.application_id or "APP-UNKNOWN"
            ev = row.dependency_evidence
            conf = "High" if ev.startswith("APM") else "Low"
            add("application", app_id, row.instance_id, "reads/writes",
                "JDBC (connection pool)" if row.db_engine == "Oracle" else "ODBC / ADO.NET",
                "Critical" if row.environment == "Production" else "Low", ev, conf,
                "Dormant" if row.instance_id in idle else "Active")
        prod = known[(known.environment == "Production") & (~known.instance_id.isin(idle))
                     & (~known.instance_id.isin(list(PLANTED)))]
        for row in prod.itertuples():
            if self.rng.random() < 0.45:
                peers = prod[(prod.business_service == row.business_service) & (prod.instance_id != row.instance_id)]
                if peers.empty:
                    continue
                tgt = peers.sample(1, random_state=self.rng.randint(0, 10_000)).iloc[0]
                if row.db_engine == "Oracle" and tgt.db_engine == "Oracle":
                    dtype, interface = "db_link", "Oracle DB link"
                elif row.db_engine == "SQL Server" and tgt.db_engine == "SQL Server":
                    dtype, interface = "linked_server", "SQL linked server"
                else:
                    dtype, interface = "ETL", self.rng.choice(["SSIS package", "Informatica workflow", "GoldenGate replication"])
                add("database", row.instance_id, tgt.instance_id, dtype, interface,
                    self.rng.choice(["High", "Medium"]), "DB catalogue (dba_db_links / sys.servers) + APM", "High")
        # Known cross-tier dependencies for planted demo cases
        add("database", "ORA-0006", "ORA-0001", "db_link", "Oracle DB link", "Critical",
            "DB catalogue (dba_db_links) + APM", "High")
        add("database", "MSS-0007", "ORA-0006", "ETL", "GoldenGate replication", "Critical", "APM trace + interface register", "High")
        add("application", "APP-OMS", "ORA-0005", "reads/writes", "JDBC (connection pool)", "Critical", "APM trace", "High")
        return out

    def costs(self, inst: pd.DataFrame, features: pd.DataFrame, recovery: pd.DataFrame) -> list[dict]:
        out = []
        tiers = recovery.set_index("instance_id")["criticality_tier"]
        for row in inst.itertuples():
            # Historic option usage is still licensable evidence, so all detected usage rows are costed.
            lic = licence_support_cost(row._asdict(), features[features.instance_id == row.instance_id])
            out.append(_cost(row.instance_id, "licence_support", lic, "Contract register / list-price allocation", "Medium", False))
            if row.esu_or_sustaining_support:
                if row.db_engine == "SQL Server":
                    base = max(row.physical_cores, 4) * ref.SQL_EDITION_PRICE_PER_CORE.get(row.edition, 0)
                    esu = base * ref.SQL_ESU_RATE
                    out.append(_cost(row.instance_id, "extended_security_updates", esu, "Microsoft ESU order (EA-DEMO-7781)", "High", False))
                else:
                    out.append(_cost(row.instance_id, "sustaining_support_uplift", lic * ref.ORACLE_SUSTAINING_UPLIFT,
                                     "Oracle Market-Driven Support quote (MDS-DEMO-221)", "Medium", False))
            onprem = row.server_type != "Azure VM"
            infra = row.vcpus * (420 if onprem else 576) + row.memory_gb * (12 if onprem else 0)
            out.append(_cost(row.instance_id, "infrastructure", infra, "Finance chargeback FY26" if onprem else "Azure Cost Management export", "Medium", False))
            out.append(_cost(row.instance_id, "storage", row.storage_allocated_gb * (1.8 if onprem else 1.4), "Storage chargeback FY26", "Medium", False))
            tier = tiers.get(row.instance_id, "Tier 3")
            dba = {"Tier 0": 14000, "Tier 1": 10000, "Tier 2": 6000, "Tier 3": 3500}[tier] if row.environment == "Production" else 2500
            out.append(_cost(row.instance_id, "dba_operations", dba, "Assumption: DBA rate card x effort band", "Low", True))
            fac = {"Physical": 2400, "IBM POWER LPAR": 3000, "VMware VM": 900, "Azure VM": 0}[row.server_type]
            if fac:
                out.append(_cost(row.instance_id, "dc_facilities", fac, "Assumption: DC power/space allocation", "Low", True))
        return out

    def entitlements(self, inst: pd.DataFrame, features: pd.DataFrame) -> list[dict]:
        req = required_licences(inst, features)
        adjust = {"Oracle Database Enterprise Edition": 8, "Oracle Database Standard Edition 2": 2, "Partitioning": 0,
                  "Advanced Compression": 6, "Advanced Security": -4, "Diagnostics Pack": None, "Tuning Pack": 14,
                  "Real Application Clusters": 0, "Active Data Guard": 4, "Database In-Memory": 8, "Multitenant": 0,
                  "Real Application Testing": 6, "Database Vault": 0, "SQL Server Enterprise": -8, "SQL Server Standard": 16}
        out = []
        for i, (product, info) in enumerate(sorted(req.items()), start=1):
            if product == "Diagnostics Pack":
                qty = req["Oracle Database Enterprise Edition"]["quantity"]
            else:
                qty = max(0, info["quantity"] + adjust.get(product, 0))
            annual = qty * info["unit_price"] * info["support_rate"]
            out.append(dict(
                entitlement_id=f"ENT-{i:03d}", vendor=info["vendor"], product=product, metric=info["metric"], quantity=qty,
                unit_list_price_gbp=info["unit_price"], support_rate=info["support_rate"], annual_support_gbp=round(annual, 2),
                agreement_ref=("CSI-DEMO-" if info["vendor"] == "Oracle" else "EA-DEMO-") + str(4400 + i),
                support_renewal_date=(ASSESSMENT_DATE + timedelta(days=60 + 25 * i)).isoformat(),
                source_document="Ordering document + support renewal (synthetic)", evidence_quality="High",
                data_label="SYNTHETIC-DEMO"))
        return out

    def cmdb_and_discovery(self, inst: pd.DataFrame) -> tuple[list[dict], list[dict]]:
        r = self.rng
        cmdb, disc = [], []
        engine_variants = {"Oracle": ["ORACLE", "Oracle Database", "Oracle DB"], "SQL Server": ["MS SQL", "Microsoft SQL Server", "MSSQL"]}
        env_variants = {"Production": ["PRD", "Prod", "Production"], "Pre-Production": ["UAT", "PreProd", "PPE"],
                        "Test": ["TST", "Test", "SIT"], "Development": ["DEV", "Dev", "Development"]}
        ed_short = {"Enterprise Edition": "EE", "Standard Edition 2": "SE2", "Enterprise": "Enterprise", "Standard": "Std",
                    "Developer": "Developer"}
        conflict_ed = {"EE": "SE2", "SE2": "EE", "Enterprise": "Std", "Std": "Enterprise", "Developer": "Std"}
        for row in inst.itertuples():
            if row.cmdb_ci_id:
                version_rec = (row.major_version.split(" ")[0] if row.db_engine == "Oracle" else row.major_version.split(" ")[-1])
                if version_rec == "12c":
                    version_rec = ref.LIFECYCLE["Oracle"][row.major_version]["family"]
                if row.instance_id in GAPS["version_conflict"]:
                    version_rec = "12c" if row.db_engine == "Oracle" else "2012"
                    if version_rec in row.major_version:
                        version_rec = "11g" if row.db_engine == "Oracle" else "2016"
                edition_rec = ed_short[row.edition]
                if row.instance_id in GAPS["edition_conflict"]:
                    edition_rec = conflict_ed[edition_rec]
                rec = dict(ci_id=row.cmdb_ci_id, ci_name=row.hostname.upper(), instance_name=row.instance_name,
                           db_engine=r.choice(engine_variants[row.db_engine]), version_recorded=version_rec,
                           edition_recorded=edition_rec, environment=r.choice(env_variants[row.environment]),
                           business_service=BUSINESS_SERVICES.get(row.business_service, ""), application_id=row.application_id,
                           owner=row.owner, support_group=f"DBA-{row.db_engine.split()[0].upper()}-L2",
                           lifecycle_status="In Service", last_verified=self.days_ago(30, 700).isoformat(),
                           data_label="SYNTHETIC-DEMO")
                cmdb.append(rec)
                if row.instance_id in GAPS["duplicate_ci"]:
                    dup = dict(rec, ci_id=f"CI{int(row.cmdb_ci_id[2:]) + 900}", ci_name=row.hostname.upper() + f".{DOMAIN.upper()}",
                               last_verified=self.days_ago(800, 1200).isoformat())
                    cmdb.append(dup)
            if row.discovery_source_ref:
                if row.db_engine == "Oracle":
                    ed_full = f"Oracle Database {row.major_version.split(' ')[0]} {row.edition} Release {row.version_build}"
                    collector = "Oracle Enterprise Manager 13.5 + options_packs_usage_statistics.sql"
                else:
                    ed_full = {"Enterprise": "Enterprise Edition: Core-based Licensing (64-bit)", "Standard": "Standard Edition (64-bit)",
                               "Developer": "Developer Edition (64-bit)"}[row.edition]
                    collector = "dbatools Get-DbaInstanceProperty + SERVERPROPERTY()"
                disc.append(dict(source_ref=row.discovery_source_ref, host_fqdn=f"{row.hostname}.{DOMAIN}",
                                 instance_name=row.instance_name.lower() if r.random() < 0.3 else row.instance_name,
                                 product=row.db_engine, version_build=row.version_build, edition_reported=ed_full,
                                 cpu_sockets=row.cpu_sockets, physical_cores=row.physical_cores, memory_gb=row.memory_gb,
                                 db_size_gb=row.db_size_gb, os_platform=row.os_platform, collector=collector,
                                 collected_at=row.collected_at, data_label="SYNTHETIC-DEMO"))
        # Ghost CIs: still "In Service" in CMDB but servers no longer exist
        for k, (eng, host) in enumerate([("ORACLE", "LONORA901P"), ("MS SQL", "MCRSQL902T")], start=1):
            cmdb.append(dict(ci_id=f"CI{19000 + k}", ci_name=host, instance_name="LEGACY1" if eng == "ORACLE" else "MSSQLSERVER",
                             db_engine=eng, version_recorded="11g" if eng == "ORACLE" else "2008", edition_recorded="EE" if eng == "ORACLE" else "Std",
                             environment="PRD" if k == 1 else "TST", business_service="Payments & Checkout",
                             application_id="APP-GFT" if k == 1 else "APP-DPL", owner=self.person(),
                             support_group="DBA-L2", lifecycle_status="In Service", last_verified="2023-02-14",
                             data_label="SYNTHETIC-DEMO"))
        return cmdb, disc

    def validation_sample(self, inst: pd.DataFrame, features: pd.DataFrame, deps: pd.DataFrame) -> list[dict]:
        """SME-validated sample used to measure edition / feature / dependency mapping accuracy."""
        r = self.rng
        out = []
        disc = inst[inst.discovery_source_ref != ""]
        for row in disc.sample(16, random_state=7).itertuples():
            out.append(dict(instance_id=row.instance_id, attribute="edition", system_value=row.edition,
                            validated_value=row.edition, validated_by=self.person(), validated_on=self.days_ago(1, 10).isoformat()))
        feat_rows = features.sample(16, random_state=11)
        for k, row in enumerate(feat_rows.itertuples()):
            # SME finds AWR "usage" triggered by default OEM jobs - a classic false positive
            fp = row.feature_name == "Automatic Workload Repository" and k % 3 == 0
            out.append(dict(instance_id=row.instance_id, attribute="feature", system_value=f"{row.feature_name}: used",
                            validated_value=f"{row.feature_name}: {'not used (OEM default job)' if fp else 'used'}",
                            validated_by=self.person(), validated_on=self.days_ago(1, 10).isoformat()))
        for k, row in enumerate(deps.sample(12, random_state=5).itertuples()):
            wrong = k == 4
            out.append(dict(instance_id=row.target_id, attribute="dependency", system_value=f"{row.source_id}->{row.target_id}",
                            validated_value=("interface decommissioned 2025" if wrong else f"{row.source_id}->{row.target_id}"),
                            validated_by=self.person(), validated_on=self.days_ago(1, 10).isoformat()))
        for o in out:
            o["match"] = o["system_value"] == o["validated_value"]
            o["data_label"] = "SYNTHETIC-DEMO"
        r.shuffle(out)
        return out


def _cost(iid, ctype, amount, source, quality, assumption) -> dict:
    return dict(instance_id=iid, cost_type=ctype, annual_cost_gbp=round(float(amount), 2), source=source,
                evidence_quality=quality, is_assumption=assumption, fiscal_year="FY26", data_label="SYNTHETIC-DEMO")


def oracle_processors(inst: dict, use_cluster: bool = False) -> int:
    cores = inst["cluster_physical_cores"] if use_cluster else inst["physical_cores"]
    return max(1, math.ceil(cores * ref.ORACLE_CORE_FACTOR.get(inst["cpu_architecture"], 0.5)))


def sql_licensable_cores(inst: dict) -> int:
    return max(4, int(inst["physical_cores"]))


def licence_support_cost(inst: dict, feature_rows: pd.DataFrame) -> float:
    """Annual licence support for one instance at list price (allocation basis, not a compliance position)."""
    if inst["db_engine"] == "Oracle":
        if inst["edition"] == "Standard Edition 2":
            return inst["cpu_sockets"] * ref.ORACLE_EDITION_PRICE["Standard Edition 2"] * ref.ORACLE_SUPPORT_RATE
        procs = oracle_processors(inst)
        total = procs * ref.ORACLE_EDITION_PRICE["Enterprise Edition"]
        options = {ref.ORACLE_OPTIONS[f]["option"]: ref.ORACLE_OPTIONS[f]["price"]
                   for f in feature_rows["feature_name"] if f in ref.ORACLE_OPTIONS} if len(feature_rows) else {}
        total += procs * sum(options.values())
        return total * ref.ORACLE_SUPPORT_RATE
    price = ref.SQL_EDITION_PRICE_PER_CORE.get(inst["edition"], 0)
    return sql_licensable_cores(inst) * price * ref.SQL_SA_RATE


def required_licences(inst: pd.DataFrame, features: pd.DataFrame) -> dict[str, dict]:
    """Deployment-based licence requirement per product (processor / socket / core metrics)."""
    req: dict[str, dict] = {}

    def bump(product, vendor, metric, qty, price, rate):
        e = req.setdefault(product, dict(vendor=vendor, metric=metric, quantity=0, unit_price=price, support_rate=rate))
        e["quantity"] += qty

    disc = inst.set_index("instance_id")
    for row in inst.to_dict("records"):
        if row["db_engine"] == "Oracle":
            if row["edition"] == "Enterprise Edition":
                bump("Oracle Database Enterprise Edition", "Oracle", "Processor", oracle_processors(row),
                     ref.ORACLE_EDITION_PRICE["Enterprise Edition"], ref.ORACLE_SUPPORT_RATE)
            else:
                bump("Oracle Database Standard Edition 2", "Oracle", "Socket", int(row["cpu_sockets"]),
                     ref.ORACLE_EDITION_PRICE["Standard Edition 2"], ref.ORACLE_SUPPORT_RATE)
        elif row["edition"] in ("Enterprise", "Standard"):
            bump(f"SQL Server {row['edition']}", "Microsoft", "Core", sql_licensable_cores(row),
                 ref.SQL_EDITION_PRICE_PER_CORE[row["edition"]], ref.SQL_SA_RATE)
    oracle_ids = set(inst.loc[inst.db_engine == "Oracle", "instance_id"])
    ora_feats = features[features.feature_name.isin(ref.ORACLE_OPTIONS) & features.instance_id.isin(oracle_ids)]
    for (iid, option), _ in ora_feats.groupby(["instance_id", "product_option"]):
        if iid in disc.index:
            row = disc.loc[iid].to_dict()
            price = next(v["price"] for v in ref.ORACLE_OPTIONS.values() if v["option"] == option)
            bump(option, "Oracle", "Processor", oracle_processors(row), price, ref.ORACLE_SUPPORT_RATE)
    for option in {v["option"] for v in ref.ORACLE_OPTIONS.values()}:
        price = next(v["price"] for v in ref.ORACLE_OPTIONS.values() if v["option"] == option)
        req.setdefault(option, dict(vendor="Oracle", metric="Processor", quantity=0, unit_price=price, support_rate=ref.ORACLE_SUPPORT_RATE))
    return req


def generate(out_dir: Path = DATA_DIR, seed: int = SEED) -> dict[str, pd.DataFrame]:
    """Generate every synthetic dataset and write CSV files. Returns the frames."""
    g = _Gen(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    inst = pd.DataFrame(g.instances())
    apps = pd.DataFrame([dict(application_id=a[0], application_name=a[1], business_service_id=a[2],
                              business_service=BUSINESS_SERVICES[a[2]], criticality_tier=f"Tier {a[3]}", primary_engine=a[4],
                              certified_db_versions=a[6], sourcing=a[7], business_owner=g.person(), data_label="SYNTHETIC-DEMO")
                         for a in APPLICATIONS])
    workload = pd.DataFrame(g.workload(inst))
    features = pd.DataFrame(g.feature_usage(inst))
    recovery = pd.DataFrame(g.recovery(inst))
    deps = pd.DataFrame(g.dependencies(inst, workload))
    costs = pd.DataFrame(g.costs(inst, features, recovery))
    ents = pd.DataFrame(g.entitlements(inst[inst.discovery_source_ref != ""], features))
    cmdb, disc = g.cmdb_and_discovery(inst)
    validation = pd.DataFrame(g.validation_sample(inst, features, deps))
    expected = pd.DataFrame([dict(instance_id=k, expected_action=v["_expected"][0], expected_readiness=v["_expected"][1],
                                  rationale=v["_expected"][2]) for k, v in PLANTED.items()]).sort_values("instance_id")
    frames = {
        "database_instances": inst, "applications": apps, "workload_metrics": workload, "feature_usage": features,
        "recovery_requirements": recovery, "dependencies": deps, "cost_records": costs, "license_entitlements": ents,
        "cmdb_extract": pd.DataFrame(cmdb), "discovery_scan": pd.DataFrame(disc), "validation_sample": validation,
        "expected_outcomes": expected,
    }
    for name, df in frames.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)
        log.info("Wrote %s (%d rows)", name, len(df))
    return frames


if __name__ == "__main__":
    generate()
