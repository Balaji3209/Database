# DB-OPTIMA AI — Database Estate Modernization & Licence Optimization Advisor

> Hackathon Case 4 POC · rules-first, AI-assisted · **all data is SYNTHETIC DEMO DATA**

DB-OPTIMA AI reconciles inventory and entitlement evidence for an Oracle + SQL Server estate, then finds licence and
modernization opportunities. For every database it compares **Retain / Upgrade / Consolidate / Replatform / Cloud Migrate
(Azure) / Retire** and produces an explainable decision pack. Architecture, licensing and production decisions stay with
named humans.

---

## 1. Quick start (VS Code, Windows)

```powershell
cd "file path"
python -m venv .venv                      # already created in this folder
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\init_db.py                 # (re)generate synthetic CSVs + SQLite DB, prints success measures
streamlit run app.py                      # opens http://localhost:8501
python -m pytest -q                       # 28 business-rule tests
```

VS Code: **Run and Debug** has three ready launch configs (`.vscode/launch.json`): *Run Streamlit app*,
*Regenerate synthetic data + DB*, *Run tests*. Select interpreter `.venv\Scripts\python.exe`.

### Azure OpenAI (optional)
Copy `.env.example` → `.env` and set `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`.
Without it (or when the call fails, or **privacy mode** is on) the app uses deterministic rules-based explanations — every
number and recommendation is identical either way, because the LLM never calculates anything.

---

## 2. The four screens

| Page | What it shows |
|---|---|
| **📊 Executive Dashboard** | 12 KPI cards (estate, unsupported versions, run cost, licence optimisation, savings, payback, migration-readiness, blocked items, risk, reconciliation, confidence, human decisions), the 5 challenge **success measures**, scenario impact panel, action mix, readiness, version/support status, EOS timeline, savings by lever (validated / proposed / potential), 5-yr TCO, risk heatmap, licence position, top-10 opportunities & risks, auto-generated insights |
| **🗄️ Estate & Licence Intelligence** | Inventory explorer + per-DB technical profile · CMDB ↔ discovery reconciliation & exception work-queue · licence position (entitled vs deployed), findings, option-usage matrix · NetworkX dependency graph & move groups · explainable risk scores |
| **🚀 Modernization & TCO** | Per-database decision advisor (6 options, hard constraints, weighted scores, evidence, assumptions, cost comparison, **human approval form**) · portfolio · TCO & budget-reduction simulator · migration waves roadmap |
| **🤖 AI Assistant & Reports** | Explore → Challenge → Verify → Own buttons, chat, number verification, masked-prompt viewer · Excel decision pack (15 sheets), HTML executive summary, HTML per-database decision pack · decision audit trail |

Sidebar: **what-if scenarios** (Oracle discovery down · budget −x% · privacy mode) and filters (service, engine, environment).

UI theme: dark *“Midnight Aurora”* palette (deep navy surfaces, sky-blue primary, violet accent, emerald / amber / coral
status colours) defined in `.streamlit/config.toml` and `dboptima/ui.py` (`C`, `PALETTE`, Plotly template `dboptima_dark`).
Downloaded HTML/Excel reports stay light so they print cleanly.

---

## 3. Architecture

```
 Synthetic sources (CSV)                 Intelligence services (deterministic Python)            Presentation
 ───────────────────────                 ───────────────────────────────────────────            ────────────
 cmdb_extract ─┐                          reconciliation.py  normalise + match + precedence
 discovery_scan┼─► database_instances ──► license_intel.py   entitlement position, edition fit
 feature_usage │   (common model)         dependency_intel.py NetworkX graph, move groups         Streamlit (4 pages)
 workload      │                          risk_intel.py      6-category explainable risk     ──► Excel / HTML packs
 recovery (BIA)│                          decision_engine.py hard constraints → 6-option score    SQLite audit trail
 dependencies  │                          tco.py             TCO, budget scenario, waves
 cost_records  │                          ai_advisor.py      masked fact pack → Azure OpenAI
 entitlements ─┘                                             (explain/challenge) → verify numbers
                     pipeline.py orchestrates · database.py persists (SQLite → PostgreSQL-ready schema.sql)
```

Design principles: **rules first, AI second** · hard constraints before scoring · every figure traceable to evidence ·
graceful degradation when a source is missing · humans own decisions (AI cannot approve; blocked items cannot be approved).

Production path: FastAPI service layer, PostgreSQL, Azure App Service, Key Vault for secrets, Entra ID sign-in, real
collectors running under read-only accounts.

---

## 4. Synthetic dataset (`data/synthetic/`)

150 instances (75 Oracle, 75 SQL Server), 2 business services (*Payments & Checkout*, *Supply Chain & Inventory*),
16 applications, Prod / Pre-Prod / Test / Dev, DC-London, DC-Manchester and Azure UK South. Seeded (`SEED=42`) so the
demo is reproducible. Every row carries `data_label = SYNTHETIC-DEMO`.

| File | Rows | Represents | Key technical fields |
|---|---|---|---|
| `database_instances.csv` | 150 | Normalised common model | version build, patch (RU/CU), edition, sockets/cores/vCPU, VMware cluster cores, CPU architecture (x86/POWER), memory, storage, RAC/FCI/AG, Data Guard/ADG/log shipping, backup tool, charset/collation, PL/SQL·T-SQL object count, DB links/linked servers, Java/AQ, PDB count, CLR, FILESTREAM, cross-DB, SQL Agent, SSIS, classification (PCI/PII), residency |
| `cmdb_extract.csv` | 151 | ServiceNow-style CMDB | free-text engine/env/edition/version, owner, app, lifecycle |
| `discovery_scan.csv` | 148 | OEM 13.5 / dbatools collectors | FQDN, `SERVERPROPERTY`-style edition strings, build, cores |
| `feature_usage.csv` | 112 | `DBA_FEATURE_USAGE_STATISTICS`, `sys.dm_db_persisted_sku_features` | option/pack, detected usages, currently used, first/last use |
| `workload_metrics.csv` | 150 | AWR / Query Store / perfmon (30 days) | CPU avg/p95, memory, IOPS p95, sessions, connections 90d, growth |
| `recovery_requirements.csv` | 150 | BIA register | tier, RPO/RTO (some missing), backup schedule, last restore test, DR site |
| `dependencies.csv` | 163 | APM, DB catalogue, CMDB relationships | app→DB, DB links, linked servers, ETL/GoldenGate, status, confidence |
| `license_entitlements.csv` | 15 | Ordering documents / EA | product, metric (Processor/Socket/Core), quantity, support £, renewal |
| `cost_records.csv` | 768 | Finance chargeback + contracts | licence support, ESU, sustaining uplift, infra, storage, DBA, DC (assumption flag) |
| `applications.csv` | 16 | App register | tier, vendor-certified DB versions, sourcing |
| `validation_sample.csv` | 44 | SME validation sample | system vs validated edition / feature / dependency |
| `expected_outcomes.csv` | 15 | Test oracle | planted cases with the expected action & readiness |

**Deliberate data-quality issues:** 2 shadow instances (not in CMDB) · 2 ghost CIs · 2 undiscovered instances ·
1 duplicate CI · 11 edition/version conflicts · 4 missing owners / 3 missing applications · 11 unknown dependency maps · 9 unknown RPO/RTO ·
historic option usage · Diagnostics Pack detected on SE2 · AWR false positives found by SME validation.

**Planted demo cases** (all verified by tests):

| Instance | Situation | Expected |
|---|---|---|
| ORA-0001 | Oracle 11.2.0.4 EE, heavy PL/SQL, options in use | Upgrade · Ready |
| ORA-0002 | 19c EE, zero EE options, 1 socket | Replatform → SE2 · Ready |
| ORA-0003 | Test DB idle 210 days, no dependants | Retire · Ready |
| ORA-0004 | Same as ORA-0002 but dependencies unknown | Replatform · **Blocked** |
| ORA-0005 | 12.1 unsupported, RPO/RTO unknown | Upgrade · Conditional |
| ORA-0006 | Tier-0 RAC + ADG, PCI, 12.2 | Upgrade · Ready (RAC not supported on Azure VMs) |
| ORA-0007 | Small SE2, 150 PL/SQL objects | Replatform → Azure PostgreSQL · Conditional |
| MSS-0001 | SQL 2014 paying ESU, cross-DB + Agent | Cloud Migrate → Azure SQL MI · Ready |
| MSS-0002 | SQL 2019 Enterprise, no Enterprise features | Replatform → Standard · Ready |
| MSS-0003..06 | 4 low-utilisation Standard test instances | Consolidate · Ready |
| MSS-0007 | SQL 2014 ESU, residency *On-Premises Only* | Upgrade · Ready (cloud hard-fail) |
| MSS-0008 | Idle production DB | Retire · Conditional (owner sign-off) |

---

## 5. How the decision engine works

1. **Hard constraints** (option becomes *Not feasible* / *Blocked*): data residency without an approved Azure region · RAC → only
   Oracle Database@Azure · PL/SQL > 800 objects, RAC or Java/AQ → no PostgreSQL · EE options in use or >2 sockets / >16 threads
   → no SE2 · Enterprise-only features or >24 cores / >128 GB → no SQL Standard · active connections or dependants → no Retire ·
   **unknown dependencies or RPO/RTO → any migration is *Blocked*, never "ready"**.
2. **Scoring** (0–100): value 35% (5-yr net benefit ÷ 5-yr run cost) · risk reduction 30% · delivery feasibility 20%
   (complexity from code objects, links, RAC, charset, size…) · strategic fit 15% (Azure preferred).
3. **Value gate:** a change with no positive 5-year case can only beat *Retain* if it fixes an unsupported / near-EOS version;
   such cases are labelled *“Risk-driven”*.
4. **Readiness:** Ready · Conditional (named human checks, e.g. app certification, PCI landing zone, Data Guard → Dbvisit) · Blocked.
5. **Confidence:** evidence-quality weighted (inventory 25%, dependencies 20%, workload 15%, features 15%, recovery 15%, cost 10%).

Key licensing rules: Oracle core factor (x86 0.5 / POWER 1.0), SE2 per socket; Oracle authorised-cloud policy (2 vCPU = 1
processor, no core factor); VMware soft-partitioning exposure flagged; SQL per core (min 4), post-2016 SP1 feature parity,
Developer edition for non-prod, ESU at 75% of licence, free ESUs on Azure VMs, Azure Hybrid Benefit compared with
licence-included pricing. **The tool never declares compliance** — positions are indicative and flagged for SME validation.

---

## 6. Success measures (live on the dashboard)

| Measure | Target | Result on synthetic estate | Definition |
|---|---|---|---|
| Inventory reconciliation | ≥ 95% | **95.3%** (143/150) | owner, application, version, edition & lifecycle all resolved |
| Mapping accuracy (SME-validated) | ≥ 90% | **95.5%** (42/44) | system vs SME on edition / feature / dependency sample |
| Addressable licence/support optimisation | 10–15% | **18.3%** proposed (+14.3% potential) | Ready non-cloud licence levers + surplus entitlement support ÷ £5.72M spend |
| Migration-ready recommendations | ≥ 80% | **91.2%** | eligible (non-Retain) recommendations not Blocked |
| Traceability | 100% | **100%** | evidence + assumptions + confidence + human decision + value |

Portfolio (illustrative): run cost **£8.14M/yr → £5.84M/yr**, saving **£2.30M/yr**, one-time £3.27M, payback **17 months**,
5-yr net £8.24M. These are validated targets on synthetic data, **not** claims about a real estate.

---

## 7. Demo script for the jury (≈7 minutes)

1. **Dashboard (90 s):** “150 databases, 60 unsupported, £8.1M run cost.” Point at the 5 success measures and the
   *validated / proposed / potential* split — we never present assumptions as savings.
2. **Estate & Licence (90 s):** Reconciliation tab → shadow/ghost/duplicate work-queue. Licence tab → Diagnostics Pack bought
   for all EE processors (shelfware), VMware exposure *flagged, not judged*. Dependencies tab → red nodes = no evidence.
3. **Modernization (2 min):** Decision advisor → **ORA-0006** (RAC → Exadata only, upgrade first) → **MSS-0001** (ESU → Azure SQL MI,
   AHB vs licence-included) → **ORA-0004** (best option *Blocked*; try to approve it — the app refuses). Record an approval on
   ORA-0001 to show the audit trail.
4. **What-if scenarios (90 s):** toggle *Oracle discovery unavailable* → 74 DBs on stale snapshot, confidence −31 pts, licence
   savings drop to 9.9% because we won’t claim savings on stale evidence. Toggle *budget −20%* → mandatory risk items still
   funded, 99.9% of savings retained, 16 deferred items listed. Toggle *privacy mode* → AI blocked, results unchanged.
5. **AI & Reports (60 s):** *Challenge* on ORA-0006, show the masked prompt and the number-verification badge; download the
   Excel decision pack.

---

## 8. Responsible AI & security

Synthetic data only · read-only discovery accounts by design (`SELECT_CATALOG_ROLE`, `VIEW SERVER STATE`) · hostnames,
instance/database names and people pseudonymised before any AI call, emails redacted, prompts logged by hash ·
privacy mode disables the AI layer · AI numbers verified against the fact pack · no automatic migrations ·
named human decisions with role and rationale stored in `decision_audit` · secrets in `.env` (Key Vault in Azure).

## 9. Limitations

Prices, lifecycle dates and Azure rates are illustrative and must be validated against vendor documentation and contracts.
Collectors are simulated; the schema and normalisation logic are designed for real OEM / dbatools / CMDB feeds.
PostgreSQL and MySQL sources are supported by the extensible model, but the pilot doesn't implement them.
