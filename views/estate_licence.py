"""Page 2 - Estate & Licence Intelligence: inventory, reconciliation, licensing, dependencies, risk."""
import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dboptima.license_intel import DISCLAIMER
from dboptima.ui import C, COLORWAY, HEAT_BLUE, PALETTE, apply_filters, chart, gbp, get_analysis, hero, money_col, service_name

a = get_analysis()
inst = apply_filters(a.data["database_instances"])
ids = set(inst.instance_id)

hero("Estate & Licence Intelligence",
     "Discovery → normalisation → CMDB reconciliation → licence position → dependency graph → explainable risk")

t1, t2, t3, t4, t5 = st.tabs(["🗂️ Inventory explorer", "🔁 Reconciliation", "📜 Licence intelligence", "🕸️ Dependencies", "⚠️ Risk"])

# =============================================================== Inventory
with t1:
    view = a.estate[a.estate.instance_id.isin(ids)].copy()
    view["business_service"] = view.business_service.map(service_name)
    c = st.columns([2, 1, 1, 1])
    q = c[0].text_input("Search (id, host, application, version...)", placeholder="e.g. 11.2, PGW, Azure, RAC")
    ver = c[1].multiselect("Version", sorted(view.major_version.unique()))
    life = c[2].multiselect("Support status", ["Unsupported", "Approaching EOS", "Extended Support", "Supported"])
    ed = c[3].multiselect("Edition", sorted(view.edition.unique()))
    if q:
        mask = view.astype(str).apply(lambda col: col.str.contains(q, case=False, regex=False)).any(axis=1)
        view = view[mask]
    if ver:
        view = view[view.major_version.isin(ver)]
    if life:
        view = view[view.lifecycle_status.isin(life)]
    if ed:
        view = view[view.edition.isin(ed)]
    m = st.columns(6)
    m[0].metric("Instances", len(view))
    m[1].metric("Total cores", int(view.physical_cores.sum()))
    m[2].metric("Memory (TB)", f"{view.memory_gb.sum() / 1024:.1f}")
    m[3].metric("Data (TB)", f"{view.db_size_gb.sum() / 1024:.1f}")
    m[4].metric("Missing owner", int((view.owner == "").sum()))
    m[5].metric("Unknown dependencies", int((view.dependency_evidence == "None").sum()))
    cols = ["instance_id", "db_engine", "hostname", "instance_name", "major_version", "version_build", "patch_level", "edition",
            "environment", "business_service", "application_id", "owner", "server_type", "os_platform", "physical_cores",
            "vcpus", "memory_gb", "db_size_gb", "cluster_type", "ha_dr_config", "cpu_p95_pct", "memory_used_pct",
            "connections_90d", "criticality_tier", "rpo_minutes", "rto_minutes", "data_classification", "data_residency",
            "lifecycle_status", "support_end", "risk_band", "recommended_action", "readiness"]
    st.dataframe(view[cols], hide_index=True, width="stretch", height=420,
                 column_config={"cpu_p95_pct": st.column_config.ProgressColumn("CPU p95 %", min_value=0, max_value=100, format="%.0f"),
                                "memory_used_pct": st.column_config.ProgressColumn("Mem %", min_value=0, max_value=100, format="%.0f")})
    st.download_button("⬇️ Download filtered inventory (CSV)", view[cols].to_csv(index=False).encode(), "inventory_filtered.csv", "text/csv")

    with st.expander("🔬 Technical profile of a single database", expanded=False):
        pick = st.selectbox("Instance", view.instance_id.tolist() or inst.instance_id.tolist(), key="inv_pick")
        row = a.data["database_instances"].set_index("instance_id").loc[pick]
        w = a.data["workload_metrics"].set_index("instance_id").loc[pick]
        f = a.data["feature_usage"][a.data["feature_usage"].instance_id == pick]
        cc = st.columns(3)
        cc[0].markdown(f"**Platform**  \n{row.db_engine} `{row.version_build}` {row.patch_level}  \n{row.edition}  \n"
                       f"{row.os_platform} · {row.server_type} · {row.cpu_architecture}  \n"
                       f"{row.cpu_sockets} socket(s) · {row.physical_cores} cores · {row.vcpus} vCPU · {row.memory_gb:.0f} GB  \n"
                       f"Cluster: {row.cluster_type} · HA/DR: {row.ha_dr_config}  \nBackup: {row.backup_method}")
        cc[1].markdown(f"**Workload (30 days)**  \nCPU avg {w.cpu_avg_pct}% · p95 {w.cpu_p95_pct}%  \nMemory {w.memory_used_pct}%  \n"
                       f"IOPS p95 {w.iops_p95:,}  \nPeak sessions {w.peak_sessions}  \nConnections/90d {w.connections_90d:,}  \n"
                       f"Growth {w.storage_growth_gb_month} GB/month  \nSource: {w.source}")
        cc[2].markdown(f"**Code & migration complexity**  \nCode objects (PL/SQL or T-SQL): {row.code_objects:,}  \n"
                       f"DB links / linked servers: {row.db_links_or_linked_servers}  \nCharset/collation: {row.character_set_or_collation}  \n"
                       f"PDBs: {row.pdb_count} · Java/AQ: {row.uses_java_or_aq}  \nCLR {row.uses_clr} · FILESTREAM {row.uses_filestream} · "
                       f"cross-DB {row.uses_cross_db_queries} · SSIS {row.uses_ssis}  \nClassification: {row.data_classification}  \n"
                       f"Residency: {row.data_residency}")
        if len(f):
            st.markdown("**Feature / option usage evidence**")
            st.dataframe(f.drop(columns=["instance_id"]), hide_index=True, width="stretch")

# =============================================================== Reconciliation
with t2:
    s = a.recon["summary"]
    m = st.columns(7)
    m[0].metric("Fully reconciled", f"{s['reconciliation_rate']}%", f"{s['fully_reconciled']}/{s['pilot_instances']}")
    m[1].metric("Matched CMDB↔discovery", s["matched"])
    m[2].metric("Conflicts auto-resolved", s["conflicts_resolved"])
    m[3].metric("Shadow (not in CMDB)", s["shadow"])
    m[4].metric("Ghost CIs", s["ghost"])
    m[5].metric("Not discovered", s["not_discovered"])
    m[6].metric("Duplicate CIs", s["duplicates"])
    st.info("**Precedence rules:** discovery collectors are authoritative for technical facts (version, edition, cores); "
            "CMDB is authoritative for business facts (owner, application, service). Matching key = short hostname + instance "
            "(case-insensitive, FQDN stripped). Free-text CMDB values are normalised (e.g. *PRD/Prod → Production*, *EE → Enterprise Edition*, *2014 → SQL Server 2014*).")
    l, r = st.columns([1, 1.6])
    with l:
        st_counts = a.recon["merged"].match_status.str.replace(r" \(.*\)", "", regex=True).value_counts().reset_index()
        st_counts.columns = ["status", "records"]
        fig = px.bar(st_counts, x="records", y="status", orientation="h", title="Match status (all source records)",
                     color="status", color_discrete_sequence=COLORWAY)
        fig.update_layout(height=320, showlegend=False, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="")
        chart(fig)
    with r:
        pi = a.recon["per_instance"]
        unresolved = pi[~pi.fully_reconciled]
        st.markdown(f"**Pilot instances not fully reconciled ({len(unresolved)})**")
        st.dataframe(unresolved, hide_index=True, width="stretch", height=280)
    st.markdown("**Exception work-queue (each with a recommended action)**")
    st.dataframe(a.recon["exceptions"], hide_index=True, width="stretch")

# =============================================================== Licence
with t3:
    st.warning(f"⚖️ {DISCLAIMER}")
    lp = a.licence_position
    lo = a.licence_opt
    m = st.columns(5)
    m[0].metric("Annual licence & support spend", gbp(lo["licence_support_spend"]))
    m[1].metric("Proposed optimisation", gbp(lo["proposed"]), f"{lo['proposed_pct']}% of spend")
    m[2].metric("Potential (after conditions)", gbp(lo["potential"]))
    m[3].metric("Surplus entitlement support", gbp(lp.surplus_support_gbp.sum()))
    m[4].metric("Products with potential shortfall", int((lp.delta < 0).sum()), "validate - not a finding", delta_color="off")
    l, r = st.columns([1.3, 1])
    with l:
        melt = lp.melt(id_vars="product", value_vars=["entitled", "deployed_requirement"], var_name="basis", value_name="units")
        fig = px.bar(melt, x="units", y="product", color="basis", barmode="group", orientation="h",
                     title="Entitled vs deployment-based requirement", color_discrete_map={"entitled": C["sky"], "deployed_requirement": C["orange"]})
        fig.update_layout(height=490, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="", legend_title="",
                          legend=dict(orientation="h", yanchor="top", y=-0.12, x=0))
        chart(fig)
    with r:
        fd = a.findings[a.findings.instance_id.isin(ids)]
        cat = fd.groupby("category").agg(findings=("instance_id", "count"), value=("est_annual_value_gbp", "sum")).reset_index()
        fig = px.bar(cat, x="findings", y="category", orientation="h", text="findings", title="Licence findings by category",
                     color="category", color_discrete_sequence=COLORWAY)
        fig.update_layout(height=300, showlegend=False, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="")
        chart(fig)
        st.markdown("**Licensing rules applied**")
        st.markdown("- Oracle EE: processors = cores × core factor (x86 0.5, POWER 1.0); SE2: per socket, max 2 sockets / 16 threads\n"
                    "- Oracle on Azure: 2 vCPU = 1 processor (no core factor); on VMware: soft-partitioning exposure flagged\n"
                    "- SQL Server: per core, min 4 per OSE; Standard limits 24 cores / 128 GB; Developer edition for non-prod\n"
                    "- Feature usage from `DBA_FEATURE_USAGE_STATISTICS` / `sys.dm_db_persisted_sku_features`; historic usage counted")
    st.markdown("**Licence position by product**")
    st.dataframe(lp, hide_index=True, width="stretch",
                 column_config={"annual_support_gbp": money_col("annual support"), "surplus_support_gbp": money_col("surplus support"),
                                "exposure_list_value_gbp": money_col("shortfall list value")})
    st.markdown("**Instance-level findings**")
    catsel = st.multiselect("Category", sorted(fd.category.unique()), default=sorted(fd.category.unique()))
    st.dataframe(fd[fd.category.isin(catsel)], hide_index=True, width="stretch",
                 column_config={"est_annual_value_gbp": money_col("est. value/yr")})
    opt = a.data["feature_usage"][a.data["feature_usage"].instance_id.isin(ids)]
    opt = opt[opt.instance_id.str.startswith("ORA")]
    if len(opt):
        mat = pd.crosstab(opt.instance_id, opt.product_option)
        fig = px.imshow(mat.T, color_continuous_scale=HEAT_BLUE, aspect="auto", title="Oracle option & pack usage matrix (instances × options)")
        fig.update_layout(height=380, margin=dict(t=50, b=10, l=10, r=10), coloraxis_showscale=False)
        chart(fig)

# =============================================================== Dependencies
with t4:
    g = a.graph
    prof = a.dep_profiles[a.dep_profiles.instance_id.isin(ids)]
    m = st.columns(5)
    m[0].metric("Graph nodes", g.number_of_nodes())
    m[1].metric("Dependencies", g.number_of_edges())
    m[2].metric("DB-to-DB interfaces", sum(1 for u, v in g.edges if g.nodes[u].get("kind") == "database"))
    m[3].metric("Move groups", len(set(a.move_groups.values())))
    m[4].metric("Unknown dependencies", int((~prof.dependencies_known).sum()))
    svc = st.radio("Business service", ["Payments & Checkout", "Supply Chain & Inventory", "All"], horizontal=True)
    keep = {n for n, d in g.nodes(data=True)
            if svc == "All" or service_name(d.get("service", "")) == svc or d.get("service") == svc}
    keep = {n for n in keep if g.nodes[n].get("kind") == "application" or n in ids}
    sub = g.subgraph(keep).copy()
    sub.remove_nodes_from([n for n in list(sub) if sub.degree(n) == 0 and g.nodes[n].get("evidence") != "None"])
    # Deterministic hub layout: each application at the centre of its own cluster of databases;
    # databases with no dependency evidence are parked in a separate column on the right.
    owner_app = a.data["database_instances"].set_index("instance_id").application_id.to_dict()
    apps_in = sorted([n for n in sub if sub.nodes[n].get("kind") == "application"])
    pos = {}
    cols_n = max(1, math.ceil(math.sqrt(len(apps_in))))
    for k, app_id in enumerate(apps_in):
        cx, cy = (k % cols_n) * 3.0, -(k // cols_n) * 3.0
        pos[app_id] = (cx, cy)
        members = sorted(d for d in sub.successors(app_id) if sub.nodes[d].get("kind") == "database"
                         and owner_app.get(d) in (app_id, "", None))
        for j, dbn in enumerate(members):
            ang = 2 * math.pi * j / max(len(members), 1)
            pos[dbn] = (cx + 1.1 * math.cos(ang), cy + 1.1 * math.sin(ang))
    orphans = [n for n in sub if n not in pos]
    unknown = [n for n in orphans if sub.nodes[n].get("evidence") == "None"]
    others = [n for n in orphans if n not in unknown]
    right = cols_n * 3.0 + 0.5
    for j, n in enumerate(others):
        pos[n] = (right, -j * 0.45)
    for j, n in enumerate(unknown):
        pos[n] = (right + 1.5, -j * 0.45)
    ex, ey = [], []
    for u, v in sub.edges:
        ex += [pos[u][0], pos[v][0], None]
        ey += [pos[u][1], pos[v][1], None]
    fig = go.Figure(go.Scatter(x=ex, y=ey, mode="lines", line=dict(color=C["slate"], width=1), hoverinfo="none"))
    if unknown:
        fig.add_annotation(x=right + 1.5, y=1.4, text="<b>No dependency<br>evidence</b>", showarrow=False, font=dict(color=C["red"]))
    if others:
        fig.add_annotation(x=right, y=0.6, text="<b>Other</b>", showarrow=False, font=dict(color=C["muted"]))
    for kind, symbol in (("application", "square"), ("database", "circle")):
        nodes = [n for n in sub if sub.nodes[n].get("kind") == kind]
        colours = []
        for n in nodes:
            d = sub.nodes[n]
            colours.append(C["text"] if kind == "application" else (C["red"] if d.get("evidence") == "None" else PALETTE.get(d.get("engine"), C["muted"])))
        fig.add_trace(go.Scatter(
            x=[pos[n][0] for n in nodes], y=[pos[n][1] for n in nodes], mode="markers+text" if kind == "application" else "markers",
            text=[sub.nodes[n].get("label", n) for n in nodes], textposition="top center", name=kind.title(),
            marker=dict(symbol=symbol, size=[14 if kind == "application" else 8 + 2 * sub.degree(n) for n in nodes], color=colours,
                        line=dict(width=1, color=C["bg"])),
            hovertext=[f"{n}<br>{sub.nodes[n].get('label')}<br>degree {sub.degree(n)}" for n in nodes], hoverinfo="text"))
    fig.update_layout(height=620, showlegend=False, margin=dict(t=30, b=10, l=10, r=10), xaxis=dict(visible=False), yaxis=dict(visible=False),
                      plot_bgcolor="rgba(0,0,0,0)")
    chart(fig)
    st.caption("■ applications (cluster centres) · ● databases (orange Oracle, blue SQL Server, **red = no dependency evidence**). "
               "Lines crossing between clusters are DB links / linked servers / ETL / replication. Node size = number of connections.")
    l, r = st.columns(2)
    with l:
        from dboptima.dependency_intel import critical_nodes
        st.markdown("**Most connected (critical) nodes**")
        st.dataframe(critical_nodes(g, 10), hide_index=True, width="stretch")
    with r:
        st.markdown("**Databases with missing or weak dependency evidence**")
        weak = prof[prof.dependency_evidence_quality != "High"][["instance_id", "dependency_evidence_quality", "active_dependants", "upstream_dependencies"]]
        st.dataframe(weak, hide_index=True, width="stretch", height=300)
    st.markdown("**Dependency register**")
    st.dataframe(a.data["dependencies"][a.data["dependencies"].target_id.isin(ids)], hide_index=True, width="stretch", height=280)

# =============================================================== Risk
with t5:
    rk = a.estate[a.estate.instance_id.isin(ids)]
    m = st.columns(4)
    for col, band in zip(m, ["Critical", "High", "Medium", "Low"]):
        col.metric(f"{band} risk", int((rk.risk_band == band).sum()))
    l, r = st.columns(2)
    with l:
        costs = a.data["cost_records"].groupby("instance_id").annual_cost_gbp.sum().rename("annual_cost").reset_index()
        sc = rk.merge(costs, on="instance_id")
        fig = px.scatter(sc, x="risk_score", y="annual_cost", color="risk_band", symbol="db_engine", color_discrete_map=PALETTE,
                         hover_data=["instance_id", "major_version", "environment", "recommended_action"],
                         title="Risk vs annual cost - top-right = act first")
        fig.update_layout(height=400, margin=dict(t=50, b=10, l=10, r=10), legend_title="")
        chart(fig)
    with r:
        cats = ["risk_lifecycle", "risk_availability", "risk_recoverability", "risk_security", "risk_licence", "risk_evidence"]
        avg = rk[cats].mean().rename(lambda c: c.replace("risk_", "").title()).reset_index()
        avg.columns = ["category", "avg"]
        fig = go.Figure(go.Scatterpolar(r=avg["avg"], theta=avg["category"], fill="toself", line_color=C["red"]))
        fig.update_layout(title="Risk profile (average score by category)", height=400, margin=dict(t=50, b=10, l=40, r=40),
                          polar=dict(radialaxis=dict(range=[0, 100])))
        chart(fig)
    st.caption("Weights: lifecycle 25% · recoverability 20% · availability 15% · security 15% · evidence 15% · licence 10%. "
               "Every score carries its reasons below - no black box.")
    st.dataframe(rk.sort_values("risk_score", ascending=False)[
        ["instance_id", "db_engine", "major_version", "environment", "criticality_tier", "lifecycle_status", "support_end",
         "risk_score", "risk_band", "risk_reasons"]], hide_index=True, width="stretch", height=400,
        column_config={"risk_score": st.column_config.ProgressColumn("risk", min_value=0, max_value=100, format="%.0f")})
