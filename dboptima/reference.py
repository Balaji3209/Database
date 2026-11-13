"""Reference catalogues used by the deterministic rules.

All dates and prices are ILLUSTRATIVE exercise assumptions modelled on public vendor
lifecycle / list-price patterns. They must be validated against current vendor
documentation and the organisation's contracts before any commercial decision.
"""
from __future__ import annotations

from datetime import date

# ----------------------------------------------------------------------------------
# Vendor support lifecycle (major version -> lifecycle facts)
# ----------------------------------------------------------------------------------
LIFECYCLE: dict[str, dict[str, dict]] = {
    "Oracle": {
        "11g R2 (11.2.0.4)": {"family": "11.2", "mainstream_end": date(2015, 1, 31), "extended_end": date(2020, 12, 31),
                              "release_type": "Legacy", "upgrade_target": "19c (19.x LTR)", "direct_upgrade": True},
        "12c R1 (12.1.0.2)": {"family": "12.1", "mainstream_end": date(2018, 7, 31), "extended_end": date(2022, 7, 31),
                              "release_type": "Legacy", "upgrade_target": "19c (19.x LTR)", "direct_upgrade": True},
        "12c R2 (12.2.0.1)": {"family": "12.2", "mainstream_end": date(2020, 11, 30), "extended_end": date(2022, 3, 31),
                              "release_type": "Legacy", "upgrade_target": "19c (19.x LTR)", "direct_upgrade": True},
        "18c (18.x)": {"family": "18", "mainstream_end": date(2021, 6, 30), "extended_end": date(2021, 6, 30),
                       "release_type": "Innovation", "upgrade_target": "19c (19.x LTR)", "direct_upgrade": True},
        "19c (19.x)": {"family": "19", "mainstream_end": date(2029, 12, 31), "extended_end": date(2032, 12, 31),
                       "release_type": "Long Term Release", "upgrade_target": "23ai (LTR)", "direct_upgrade": True},
        "21c (21.x)": {"family": "21", "mainstream_end": date(2027, 7, 31), "extended_end": date(2027, 7, 31),
                       "release_type": "Innovation", "upgrade_target": "23ai (LTR)", "direct_upgrade": True},
        "23ai (23.x)": {"family": "23", "mainstream_end": date(2031, 12, 31), "extended_end": date(2034, 12, 31),
                        "release_type": "Long Term Release", "upgrade_target": None, "direct_upgrade": True},
    },
    "SQL Server": {
        "SQL Server 2012": {"family": "11.0", "mainstream_end": date(2017, 7, 11), "extended_end": date(2022, 7, 12),
                            "release_type": "Legacy", "upgrade_target": "SQL Server 2022", "direct_upgrade": True},
        "SQL Server 2014": {"family": "12.0", "mainstream_end": date(2019, 7, 9), "extended_end": date(2024, 7, 9),
                            "release_type": "Legacy", "upgrade_target": "SQL Server 2022", "direct_upgrade": True},
        "SQL Server 2016": {"family": "13.0", "mainstream_end": date(2021, 7, 13), "extended_end": date(2026, 7, 14),
                            "release_type": "Legacy", "upgrade_target": "SQL Server 2022", "direct_upgrade": True},
        "SQL Server 2017": {"family": "14.0", "mainstream_end": date(2022, 10, 11), "extended_end": date(2027, 10, 12),
                            "release_type": "Current", "upgrade_target": "SQL Server 2022", "direct_upgrade": True},
        "SQL Server 2019": {"family": "15.0", "mainstream_end": date(2025, 2, 28), "extended_end": date(2030, 1, 8),
                            "release_type": "Current", "upgrade_target": "SQL Server 2022", "direct_upgrade": True},
        "SQL Server 2022": {"family": "16.0", "mainstream_end": date(2028, 1, 11), "extended_end": date(2033, 1, 11),
                            "release_type": "Current", "upgrade_target": None, "direct_upgrade": True},
    },
}

# Full build numbers used by the synthetic collectors (major version -> build string)
VERSION_BUILDS = {
    "11g R2 (11.2.0.4)": "11.2.0.4.0", "12c R1 (12.1.0.2)": "12.1.0.2.0", "12c R2 (12.2.0.1)": "12.2.0.1.0",
    "18c (18.x)": "18.14.0.0.0", "19c (19.x)": "19.24.0.0.0", "21c (21.x)": "21.15.0.0.0", "23ai (23.x)": "23.6.0.24.10",
    "SQL Server 2012": "11.0.7507.2", "SQL Server 2014": "12.0.6449.1", "SQL Server 2016": "13.0.6450.1",
    "SQL Server 2017": "14.0.3485.1", "SQL Server 2019": "15.0.4400.1", "SQL Server 2022": "16.0.4155.4",
}

# ----------------------------------------------------------------------------------
# Licensing catalogue (illustrative list prices in GBP, perpetual licence)
# ----------------------------------------------------------------------------------
ORACLE_SUPPORT_RATE = 0.22          # annual support as % of licence
SQL_SA_RATE = 0.25                  # annual Software Assurance as % of licence
SQL_ESU_RATE = 0.75                 # Extended Security Updates as % of licence per year (on-prem)
ORACLE_SUSTAINING_UPLIFT = 0.20     # uplift for Market-Driven / sustaining support on unsupported releases

ORACLE_CORE_FACTOR = {"x86_64": 0.5, "IBM POWER": 1.0, "SPARC": 0.5}

ORACLE_EDITION_PRICE = {             # per processor (EE) / per socket (SE2)
    "Enterprise Edition": 38000,
    "Standard Edition 2": 14000,
}
SQL_EDITION_PRICE_PER_CORE = {       # per core (sold in 2-core packs, min 4 cores per OSE)
    "Enterprise": 6050,
    "Standard": 1580,
    "Developer": 0,
    "Express": 0,
}
SE2_MAX_SOCKETS = 2
SE2_MAX_THREADS = 16
SQL_STD_MAX_CORES = 24
SQL_STD_MAX_MEMORY_GB = 128

# Oracle licensable options & management packs: DBA_FEATURE_USAGE_STATISTICS name -> option
ORACLE_OPTIONS: dict[str, dict] = {
    "Partitioning (user)": {"option": "Partitioning", "price": 9200},
    "Advanced Index Compression": {"option": "Advanced Compression", "price": 9200},
    "OLTP Table Compression": {"option": "Advanced Compression", "price": 9200},
    "Transparent Data Encryption": {"option": "Advanced Security", "price": 12000},
    "Automatic Workload Repository": {"option": "Diagnostics Pack", "price": 6000},
    "SQL Tuning Advisor": {"option": "Tuning Pack", "price": 4000},
    "Real Application Clusters (RAC)": {"option": "Real Application Clusters", "price": 18400},
    "Active Data Guard - Real-Time Query on Physical Standby": {"option": "Active Data Guard", "price": 9200},
    "In-Memory Column Store": {"option": "Database In-Memory", "price": 18400},
    "Oracle Multitenant (>3 user PDBs)": {"option": "Multitenant", "price": 14000},
    "Database Replay: Workload Capture": {"option": "Real Application Testing", "price": 9200},
    "Oracle Database Vault": {"option": "Database Vault", "price": 9200},
}

# SQL Server features that require Enterprise edition (post 2016 SP1 feature parity applied)
SQL_ENTERPRISE_FEATURES: dict[str, dict] = {
    "Always On AG - readable secondary": {"enterprise_only": True},
    "Online Index Rebuild": {"enterprise_only": True},
    "Resource Governor": {"enterprise_only": True},
    "Peer-to-Peer Replication": {"enterprise_only": True},
    "Transparent Data Encryption": {"enterprise_only_before": "SQL Server 2019"},
    "Table Partitioning": {"enterprise_only_before": "SQL Server 2016"},
    "Data Compression": {"enterprise_only_before": "SQL Server 2016"},
    "Columnstore Index": {"enterprise_only_before": "SQL Server 2016"},
}
SQL_VERSION_ORDER = ["SQL Server 2012", "SQL Server 2014", "SQL Server 2016", "SQL Server 2017",
                     "SQL Server 2019", "SQL Server 2022"]

# ----------------------------------------------------------------------------------
# Azure target catalogue (illustrative GBP rates)
# ----------------------------------------------------------------------------------
AZURE_ALLOWED_REGIONS = {
    "UK": ["UK South", "UK West"],
    "EU": ["North Europe", "West Europe"],
    "Any": ["UK South", "UK West", "North Europe", "West Europe"],
    "On-Premises Only": [],
}
AZURE_RATES = {  # per vCore (or vCPU) per month
    "Azure SQL Database (GP)": 230,
    "Azure SQL Managed Instance (GP)": 290,
    "Azure SQL Managed Instance (BC)": 780,
    "SQL Server on Azure VM": 45,              # compute only, licence via existing SA/AHB
    "Oracle on Azure VM (BYOL)": 48,           # compute only, licence BYOL
    "Oracle Database@Azure (Exadata)": 520,    # infrastructure, licence BYOL
    "Azure Database for PostgreSQL (Flexible)": 55,
}
AHB_DISCOUNT = 0.60            # Azure Hybrid Benefit compute rate as % of licence-included rate
AZURE_STORAGE_GB_YEAR = 1.4
MI_VCORE_SIZES = [4, 8, 16, 24, 32, 40, 64, 80]

# One-time cost model (GBP) - base + complexity-driven effort
ONE_TIME_COST = {
    "Retain": (0, 0),
    "Upgrade": (12000, 350),
    "Consolidate": (8000, 150),
    "Replatform-Edition": (10000, 120),
    "Replatform-Engine": (15000, 0),   # plus 25 per PL/SQL object + 6 per GB (see decision_engine)
    "Cloud Migrate-PaaS": (22000, 600),
    "Cloud Migrate-IaaS": (15000, 300),
    "Retire": (4000, 0),
}

# Operating-system lifecycle (illustrative) - OS end of support is a co-dependent risk
OS_LIFECYCLE = {
    "Windows Server 2012 R2": date(2023, 10, 10),
    "Windows Server 2016": date(2027, 1, 12),
    "Windows Server 2019": date(2029, 1, 9),
    "Windows Server 2022": date(2031, 10, 14),
    "RHEL 7.9": date(2024, 6, 30),
    "RHEL 8.8": date(2029, 5, 31),
    "Oracle Linux 7.9": date(2024, 12, 31),
    "Oracle Linux 8.9": date(2029, 7, 31),
    "AIX 7.2": date(2026, 4, 30),
    "AIX 7.3": date(2030, 11, 30),
}

OPTIONS = ["Retain", "Upgrade", "Consolidate", "Replatform", "Cloud Migrate", "Retire"]
MIGRATION_OPTIONS = {"Consolidate", "Replatform", "Cloud Migrate", "Retire"}
