"""Page 3 - Modernization & TCO: six-option decision engine, human approval, portfolio, TCO, budget and waves."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dboptima import database, reference as ref
from dboptima.decision_engine import ASSUMPTIONS, WEIGHTS
from dboptima.tco import budget_scenario
from dboptima.ui import C, PALETTE, apply_filters, chart, gbp, get_analysis, hero, money_col, refresh, scenario

a = get_analysis()
recs = apply_filters(a.recs)
ids = recs.instance_id.tolist()

hero("Modernization & TCO",
     "Hard constraints → six-option scoring → evidence & confidence → human decision → TCO, budget and migration waves")

t1, t2, t3, t4 = st.tabs(["🧠 Decision advisor", "📋 Portfolio", "💷 TCO & budget", "🗓️ Migration waves"])

# =============================================================== Decision advisor (per database)
with t1:
    planted = a.data["expected_outcomes"].instance_id.tolist()
    default = "ORA-0001" if "ORA-0001" in ids else (ids[0] if ids else None)
    if default is None:
        st.warning("No instances match the current filters.")
        st.stop()
    c = st.columns([1.3, 2])
    iid = c[0].selectbox("Database instance", ids, index=ids.index(default), key="adv_iid",
                         help="Demo tip: ORA-0001, ORA-0004, ORA-0006, MSS-0001, MSS-0007, MSS-0008 illustrate key rules.")
    c[1].caption("**Demo cases with known expected outcomes:** " + ", ".join(planted))
    rec = a.recs.set_index("instance_id").loc[iid]
    inst = a.data["database_instances"].set_index("instance_id").loc[iid]
    risk = a.risk.set_index("instance_id").loc[iid]
    opts = a.options[a.options.instance_id == iid].copy()

    colour = PALETTE[rec.readiness]
    st.markdown(
        f"<div class='kpi' style='border-left:6px solid {colour}'><div class='label'>{iid} · {inst.db_engine} {inst.major_version} "
        f"{inst.edition} · {inst.environment} · {risk.lifecycle_status}</div>"
        f"<div class='value'>{rec.recommended_action} → {rec.target_platform}</div>"
        f"<div class='sub'>Readiness <b style='color:{colour}'>{rec.readiness}</b> · score {rec.score} (runner-up {rec.runner_up} {rec.runner_up_score}) · "
        f"confidence <b>{rec.confidence} ({rec.confidence_pct}%)</b> · human decision <b>{rec.human_decision}</b></div>"
        f"<div class='sub'>{rec.rationale}</div><div class='sub'><b>Next action:</b> {rec.next_action}</div></div>",
        unsafe_allow_html=True)
    st.write("")
    m = st.columns(5)
    m[0].metric("Current annual cost", gbp(rec.current_annual))
    m[1].metric("Target annual cost", gbp(rec.target_annual), gbp(-rec.annual_saving), delta_color="inverse")
    m[2].metric("One-time cost", gbp(rec.one_time_cost))
    m[3].metric("Payback", f"{rec.payback_months:.0f} months" if pd.notna(rec.payback_months) else "n/a")
    m[4].metric("5-year net benefit", gbp(rec.net_5yr))

    l, r = st.columns([1.2, 1])
    with l:
        comp = opts.melt(id_vars=["option", "status"], value_vars=[f"c_{k}" for k in WEIGHTS], var_name="criterion", value_name="raw")
        comp["criterion"] = comp.criterion.str[2:]
        comp["weighted"] = comp.apply(lambda x: (x.raw or 0) * WEIGHTS[x.criterion] if x.status != "Not feasible" else 0, axis=1)
        comp["label"] = comp.option + " (" + comp.status + ")"
        fig = px.bar(comp, x="weighted", y="label", color="criterion", orientation="h",
                     title="Option scores - weighted contribution by criterion",
                     color_discrete_map={"value": C["green"], "risk_reduction": C["red"], "feasibility": C["sky"], "strategic_fit": C["violet"]})
        fig.update_layout(height=360, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="", xaxis_title="score (0-100)",
                          yaxis={"categoryorder": "total ascending"}, legend=dict(orientation="h", y=-0.2), legend_title="")
        chart(fig)
    with r:
        cost = opts[opts.status != "Not feasible"][["option", "current_annual", "target_annual", "one_time_cost"]]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=cost.option, y=cost.current_annual, name="Current / yr", marker_color=C["slate"]))
        fig.add_trace(go.Bar(x=cost.option, y=cost.target_annual, name="Target / yr", marker_color=C["green"]))
        fig.add_trace(go.Bar(x=cost.option, y=cost.one_time_cost, name="One-time", marker_color=C["amber"]))
        fig.update_layout(barmode="group", title="Cost comparison of feasible options (£)", height=360,
                          margin=dict(t=50, b=10, l=10, r=10), legend=dict(orientation="h", y=-0.2))
        chart(fig)

    st.markdown("**All six options - hard constraints, conditions and drivers**")
    st.dataframe(opts[["option", "status", "score", "target_platform", "annual_saving", "one_time_cost", "constraints", "conditions", "drivers"]]
                 .sort_values("score", ascending=False), hide_index=True, width="stretch",
                 column_config={"annual_saving": money_col("saving/yr"), "one_time_cost": money_col("one-time"),
                                "score": st.column_config.ProgressColumn("score", min_value=0, max_value=100, format="%.1f")})
    l, r = st.columns([1.4, 1])
    with l:
        st.markdown("**Evidence trail**")
        ev = a.evidence[a.evidence.instance_id == iid][["evidence_type", "quality", "source", "fact", "collected_at"]]
        st.dataframe(ev, hide_index=True, width="stretch")
    with r:
        st.markdown("**Assumptions**")
        for x in ASSUMPTIONS:
            st.markdown(f"- {x}")
        st.markdown(f"**Risk:** {risk.risk_band} ({risk.risk_score}) - {risk.risk_reasons or 'none'}")

    st.markdown("#### 🧑‍⚖️ Human decision (Own)")
    with st.form("decision", clear_on_submit=True):
        fc = st.columns([1, 1, 1, 2])
        who = fc[0].text_input("Decision-maker name *")
        role = fc[1].selectbox("Role", ["Enterprise Architect", "Database Architect", "Licensing SME", "Service Owner", "CIO delegate"])
        decision = fc[2].selectbox("Decision", ["Approved", "Rejected", "Deferred", "More evidence requested"])
        action = fc[3].selectbox("Decided action", ref.OPTIONS, index=ref.OPTIONS.index(rec.recommended_action))
        comment = st.text_area("Rationale / conditions accepted", height=70)
        submitted = st.form_submit_button("Record decision", type="primary")
        if submitted:
            if decision == "Approved" and rec.readiness == "Blocked":
                st.error("Cannot approve a Blocked recommendation - close the evidence gaps first (hard constraint).")
            elif not who.strip():
                st.error("A named decision-maker is required.")
            else:
                database.record_decision(rec.recommendation_id, iid, decision, action, who, role, comment)
                refresh()
                st.success(f"Decision recorded in the audit trail: {decision} by {who} ({role}).")
                st.rerun()
    hist = database.decision_log()
    hist = hist[hist.instance_id == iid]
    if len(hist):
        st.dataframe(hist, hide_index=True, width="stretch")

# =============================================================== Portfolio
with t2:
    m = st.columns(5)
    m[0].metric("Recommendations", len(recs))
    m[1].metric("Ready", int((recs.readiness == "Ready").sum()))
    m[2].metric("Conditional", int((recs.readiness == "Conditional").sum()))
    m[3].metric("Blocked", int((recs.readiness == "Blocked").sum()))
    m[4].metric("Avg confidence", f"{recs.confidence_pct.mean():.0f}%")
    l, r = st.columns(2)
    with l:
        tgt = recs[recs.recommended_action.isin(["Cloud Migrate", "Replatform"])].copy()
        tgt["platform"] = tgt.target_platform.str.replace(r" \(UK.*\)$| \(North.*\)$| \(West.*\)$", "", regex=True)
        fig = px.sunburst(tgt, path=["recommended_action", "platform"], title="Target platforms (Cloud Migrate & Replatform)")
        fig.update_layout(height=380, margin=dict(t=50, b=10, l=10, r=10))
        chart(fig)
    with r:
        fig = px.histogram(recs, x="confidence_pct", color="confidence", nbins=20, title="Confidence distribution",
                           color_discrete_map={"High": C["green"], "Medium": C["amber"], "Low": C["red"]})
        fig.update_layout(height=380, margin=dict(t=50, b=10, l=10, r=10), legend_title="")
        chart(fig)
    act = st.multiselect("Action", ref.OPTIONS, default=[o for o in ref.OPTIONS if o != "Retain"])
    rd = st.multiselect("Readiness", ["Ready", "Conditional", "Blocked"], default=["Ready", "Conditional", "Blocked"])
    pv = recs[recs.recommended_action.isin(act) & recs.readiness.isin(rd)]
    st.dataframe(pv[["instance_id", "db_engine", "environment", "recommended_action", "target_platform", "readiness", "confidence",
                     "score", "runner_up", "annual_saving", "one_time_cost", "payback_months", "net_5yr", "conditions", "constraints",
                     "next_action", "human_decision"]], hide_index=True, width="stretch", height=460,
                 column_config={"annual_saving": money_col("saving/yr"), "one_time_cost": money_col("one-time"), "net_5yr": money_col("5-yr net")})

# =============================================================== TCO & budget
with t3:
    t = a.tco
    m = st.columns(6)
    m[0].metric("Current annual run cost", gbp(t["current_annual"]))
    m[1].metric("Target annual run cost", gbp(t["target_annual"]), gbp(-t["annual_saving"]), delta_color="inverse")
    m[2].metric("One-time investment", gbp(t["one_time"]))
    m[3].metric("3-year net", gbp(t["net_3yr"]))
    m[4].metric("5-year net", gbp(t["net_5yr"]))
    m[5].metric("Payback", f"{t['payback_months']:.0f} months" if t["payback_months"] else "n/a")
    l, r = st.columns(2)
    with l:
        by = a.recs.groupby("recommended_action").agg(current=("current_annual", "sum"), target=("target_annual", "sum"),
                                                     one_time=("one_time_cost", "sum")).reset_index()
        fig = go.Figure()
        fig.add_trace(go.Bar(x=by.recommended_action, y=by.current, name="Current / yr", marker_color=C["slate"]))
        fig.add_trace(go.Bar(x=by.recommended_action, y=by.target, name="Target / yr", marker_color=C["green"]))
        fig.add_trace(go.Bar(x=by.recommended_action, y=by.one_time, name="One-time", marker_color=C["amber"]))
        fig.update_layout(barmode="group", title="Run cost & investment by recommended action", height=380,
                          margin=dict(t=50, b=10, l=10, r=10), legend=dict(orientation="h", y=-0.2))
        chart(fig)
    with r:
        costs = a.data["cost_records"].groupby("cost_type").annual_cost_gbp.sum().reset_index()
        fig = px.pie(costs, names="cost_type", values="annual_cost_gbp", hole=0.5, title="Current run-cost composition")
        fig.update_traces(textposition="inside", textinfo="percent")
        fig.update_layout(height=400, margin=dict(t=50, b=10, l=10, r=10), legend=dict(orientation="h", yanchor="top", y=-0.05, x=0))
        chart(fig)

    st.markdown("#### ✂️ Budget reduction simulator")
    sc = scenario()
    cut = st.slider("Reduce one-time transformation budget by (%)", 0, 50, int(sc.budget_cut_pct or 20), 5, key="tco_cut")
    b = budget_scenario(a.recs, a.risk, cut)
    m = st.columns(5)
    m[0].metric("Baseline budget", gbp(b["baseline_budget"]))
    m[1].metric("Reduced budget", gbp(b["reduced_budget"]), f"-{cut}%", delta_color="off")
    m[2].metric("Funded / deferred", f"{b['funded_count']} / {b['deferred_count']}")
    m[3].metric("Mandatory risk items funded", f"{b['mandatory_funded']}/{b['mandatory_total']}")
    m[4].metric("Recurring savings retained", f"{b['saving_retained_pct']}%", gbp(b["funded_annual_saving"] - b["baseline_annual_saving"]))
    st.caption("Prioritisation rule: (1) unsupported production remediation is mandatory, (2) remaining items ranked by 5-year net "
               "benefit per £ of one-time cost, (3) blocked items are excluded until evidence is complete.")
    prog = b["programme"].copy()
    prog["cumulative_one_time"] = prog.one_time_cost.cumsum()
    fig = px.bar(prog.reset_index(drop=True).reset_index(), x="index", y="annual_saving", color="funded",
                 color_discrete_map={True: C["green"], False: C["track"]}, hover_data=["instance_id", "recommended_action", "one_time_cost"],
                 title="Programme items in priority order (green = funded within reduced budget)")
    fig.update_layout(height=320, margin=dict(t=50, b=10, l=10, r=10), xaxis_title="priority rank", yaxis_title="annual saving £")
    chart(fig)
    st.dataframe(prog[["instance_id", "recommended_action", "environment", "lifecycle_status", "mandatory", "roi", "one_time_cost",
                       "annual_saving", "funded"]], hide_index=True, width="stretch", height=300,
                 column_config={"one_time_cost": money_col("one-time"), "annual_saving": money_col("saving/yr"),
                                "roi": st.column_config.NumberColumn("5-yr ROI (x)", format="%.1f")})

# =============================================================== Waves
with t4:
    wv = apply_filters(a.waves)
    order = ["Wave 0 - Quick wins (0-3 months)", "Wave 1 - Risk remediation (3-9 months)", "Wave 2 - Modernise (6-15 months)",
             "Wave 3 - Evidence first", "No action"]
    agg = wv.groupby("wave").agg(instances=("instance_id", "count"), annual_saving=("annual_saving", "sum"),
                                 one_time=("one_time_cost", "sum")).reindex(order).dropna().reset_index()
    start = {"Wave 0": 0, "Wave 1": 3, "Wave 2": 6, "Wave 3": 1}
    end = {"Wave 0": 3, "Wave 1": 9, "Wave 2": 15, "Wave 3": 6}
    gantt = agg[agg.wave != "No action"].copy()
    gantt["start"] = gantt.wave.str[:6].map(start)
    gantt["duration"] = gantt.wave.str[:6].map(end) - gantt["start"]
    fig = go.Figure()
    for row in gantt.itertuples():
        fig.add_trace(go.Bar(y=[row.wave], x=[row.duration], base=[row.start], orientation="h", name=row.wave,
                             text=f"{int(row.instances)} DBs · {gbp(row.annual_saving)}/yr", textposition="inside"))
    fig.update_layout(title="Migration roadmap (months from approval)", height=300, showlegend=False, barmode="overlay",
                      margin=dict(t=50, b=10, l=10, r=10), xaxis_title="month", yaxis=dict(autorange="reversed"))
    chart(fig)
    st.dataframe(agg, hide_index=True, width="stretch",
                 column_config={"annual_saving": money_col("saving/yr"), "one_time": money_col("one-time")})
    st.caption("Databases connected by DB links / linked servers / ETL form *move groups* and are aligned to the same wave.")
    st.dataframe(wv[wv.wave != "No action"][["wave", "move_group", "instance_id", "recommended_action", "target_platform", "readiness",
                                             "lifecycle_status", "annual_saving", "one_time_cost"]].sort_values(["wave", "move_group"]),
                 hide_index=True, width="stretch", height=420,
                 column_config={"annual_saving": money_col("saving/yr"), "one_time_cost": money_col("one-time")})
