"""Page 1 - Executive Dashboard: the single-screen story for senior stakeholders and the jury."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dboptima import config
from dboptima.ui import C, HEAT_RED, PALETTE, apply_filters, chart, gbp, get_analysis, hero, kpi_grid, money_col, scenario, service_name

a = get_analysis()
sc = scenario()
estate = apply_filters(a.estate)
n = len(estate)
LEG = dict(orientation="h", yanchor="top", y=-0.18, x=0)

hero("Executive Dashboard",
     f"Database estate of {len(a.recs)} instances · Oracle {int((a.recs.db_engine == 'Oracle').sum())} · "
     f"SQL Server {int((a.recs.db_engine == 'SQL Server').sum())} · 2 business services · Azure as target cloud · "
     f"assessed {config.ASSESSMENT_DATE:%d %b %Y}")

if n == 0:
    st.warning("No instances match the current filters.")
    st.stop()

# ------------------------------------------------------------------ KPI row 1 - estate, risk & money
unsupported = int((estate.lifecycle_status == "Unsupported").sum())
approaching = int((estate.lifecycle_status == "Approaching EOS").sum())
cost_rows = a.data["cost_records"][a.data["cost_records"].instance_id.isin(estate.instance_id)]
run_cost = cost_rows.annual_cost_gbp.sum()
lic_cost = cost_rows[cost_rows.cost_type.isin(["licence_support", "extended_security_updates", "sustaining_support_uplift"])].annual_cost_gbp.sum()
saving = estate.annual_saving.sum()
one_time = estate.one_time_cost.sum()
payback = one_time / (saving / 12) if saving > 0 else None

kpi_grid([
    ("Instances in scope", f"{n}", f"Oracle {int((estate.db_engine == 'Oracle').sum())} · SQL {int((estate.db_engine == 'SQL Server').sum())} · "
     f"Prod {int((estate.environment == 'Production').sum())}", "blue"),
    ("Unsupported versions", f"{unsupported}", f"{100 * unsupported / n:.0f}% of estate · +{approaching} approaching EOS (<18m)", "red"),
    ("Annual run cost", gbp(run_cost), f"Licence & support {gbp(lic_cost)} ({100 * lic_cost / run_cost:.0f}%)", "blue"),
    ("Licence optimisation (proposed)", gbp(a.licence_opt["proposed"]),
     f"{a.licence_opt['proposed_pct']}% of £{a.licence_opt['licence_support_spend'] / 1e6:.2f}M spend · +{gbp(a.licence_opt['potential'])} potential", "green"),
    ("Recurring saving / yr", gbp(saving), f"{100 * saving / run_cost:.0f}% of run cost · one-time {gbp(one_time)}", "green"),
    ("Payback / 5-yr net", f"{payback:.0f} months" if payback else "n/a", f"5-yr net benefit {gbp(5 * saving - one_time)}", "green"),
])

st.write("")
# ------------------------------------------------------------------ KPI row 2 - readiness & governance
eligible = estate[estate.recommended_action != "Retain"]
ready = int((eligible.readiness == "Ready").sum())
cond = int((eligible.readiness == "Conditional").sum())
blocked = int((eligible.readiness == "Blocked").sum())
high_risk = int(estate.risk_band.isin(["Critical", "High"]).sum())
conf_avg = a.recs[a.recs.instance_id.isin(estate.instance_id)].confidence_pct.mean()
pending = int((estate.human_decision == "Pending").sum())
approved = int((estate.human_decision == "Approved").sum())

kpi_grid([
    ("Migration-ready", f"{100 * (ready + cond) / max(len(eligible), 1):.0f}%",
     f"{ready} ready · {cond} with conditions · of {len(eligible)} eligible", "green"),
    ("Blocked by evidence gaps", f"{blocked}", "Unknown dependencies / RPO-RTO - never shown as ready", "amber"),
    ("High / critical risk", f"{high_risk}", f"{int((estate.risk_band == 'Critical').sum())} critical · lifecycle, HA/DR, security", "red"),
    ("Inventory reconciled", f"{a.recon['summary']['reconciliation_rate']}%",
     f"{a.recon['summary']['conflicts_resolved']} conflicts · {a.recon['summary']['shadow']} shadow · {a.recon['summary']['ghost']} ghost", "blue"),
    ("Average confidence", f"{conf_avg:.0f}%", "Evidence-quality weighted (6 evidence types)", "blue"),
    ("Human decisions", f"{approved} approved", f"{pending} pending approval · AI never decides", "amber"),
])

# ------------------------------------------------------------------ Scenario impact
if sc.oracle_discovery_unavailable or sc.budget_cut_pct or sc.ai_privacy_strict:
    base = get_analysis(baseline=True)
    with st.container(border=True):
        st.markdown("#### 🎯 Scenario impact (vs. baseline)")
        cards, notes = [], []
        if sc.oracle_discovery_unavailable:
            ora_now = a.recs[a.recs.db_engine == "Oracle"].confidence_pct.mean()
            ora_base = base.recs[base.recs.db_engine == "Oracle"].confidence_pct.mean()
            ready_now, ready_base = int((a.recs.readiness == "Ready").sum()), int((base.recs.readiness == "Ready").sum())
            cards += [
                ("Discovery outage · stale snapshot", f"{a.recon['summary']['stale_snapshot']} DBs",
                 f"Reconciliation held at {a.recon['summary']['reconciliation_rate']}% using last-known OEM data", "amber"),
                ("Discovery outage · Oracle confidence", f"{ora_now:.0f}%", f"{ora_now - ora_base:+.1f} pts vs baseline {ora_base:.0f}%", "red"),
                ("Discovery outage · fully Ready", f"{ready_now}", f"{ready_now - ready_base:+d} vs baseline - Oracle actions now Conditional", "amber"),
                ("Discovery outage · proposed licence saving", f"{a.licence_opt['proposed_pct']}%",
                 f"was {base.licence_opt['proposed_pct']}% - no savings claimed on stale evidence", "amber"),
            ]
            notes.append("**Discovery outage:** Oracle facts fall back to the last-known OEM snapshot, evidence is down-graded to "
                         "*Low (stale)* and Oracle change actions become *Conditional*. SQL Server evidence is unaffected. "
                         "Mitigation: secondary collector (read-only SQL scripts) and CMDB precedence rules.")
        if sc.budget_cut_pct:
            b = a.budget
            cards += [
                (f"Budget -{sc.budget_cut_pct:.0f}% · funded", f"{b['funded_count']} / {b['funded_count'] + b['deferred_count']}",
                 f"£{b['reduced_budget'] / 1e6:.2f}M of £{b['baseline_budget'] / 1e6:.2f}M · mandatory {b['mandatory_funded']}/{b['mandatory_total']}", "blue"),
                (f"Budget -{sc.budget_cut_pct:.0f}% · savings retained", f"{b['saving_retained_pct']}%",
                 f"{b['deferred_count']} low-ROI items deferred · {b['deferred_risk_items']} of them carry lifecycle risk", "green"),
            ]
            notes.append("**Budget cut:** unsupported production remediation is funded first, the rest ranked by 5-year net benefit per £; "
                         "deferred lifecycle-risk items are listed in *Modernization & TCO → TCO & budget*.")
        if sc.ai_privacy_strict:
            cards.append(("Privacy mode · AI layer", "Blocked", "0 records sent to AI · all scores & figures unchanged", "green"))
            notes.append("**Privacy mode:** recommendations, scores and figures are produced by deterministic rules, so they are unchanged; "
                         "only narrative explanations switch to rules-based templates.")
        kpi_grid(cards, min_width=210)
        for n_ in notes:
            st.caption(n_)

# ------------------------------------------------------------------ Success scorecard
st.markdown("#### ✅ Challenge success measures")
cards = ""
for k, v in a.kpis.items():
    colour = C["green"] if v["met"] else C["red"]
    icon = "✅" if v["met"] else "⚠️"
    cards += (f"<div class='sc-card'><div class='t'>{v['name']}</div><div class='v' style='color:{colour}'>{icon} {v['actual']}%</div>"
              f"<div class='d'>Target {v['target']}</div><div class='d'>{v['detail']}</div></div>")
st.markdown(f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px'>{cards}</div>",
            unsafe_allow_html=True)
st.caption("Measured on the full synthetic pilot estate. Targets are validated, not assumed - figures recalculate live under each scenario.")

# ------------------------------------------------------------------ Charts row 1
l, r = st.columns([1, 1.25])
with l:
    mix = estate.recommended_action.value_counts().reset_index()
    mix.columns = ["action", "count"]
    fig = px.pie(mix, names="action", values="count", hole=0.55, color="action", color_discrete_map=PALETTE,
                 title="Recommended action mix")
    fig.update_traces(textinfo="label+value")
    fig.update_layout(height=340, margin=dict(t=50, b=10, l=10, r=10), showlegend=False)
    chart(fig)
with r:
    rd = estate.groupby(["recommended_action", "readiness"]).size().reset_index(name="count")
    fig = px.bar(rd, x="count", y="recommended_action", color="readiness", orientation="h", color_discrete_map=PALETTE,
                 title="Readiness by action (after hard constraints)",
                 category_orders={"readiness": ["Ready", "Conditional", "Blocked"]})
    fig.update_layout(height=340, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="", legend_title="", legend=LEG)
    chart(fig)

# ------------------------------------------------------------------ Charts row 2 - lifecycle
l, r = st.columns([1.25, 1])
with l:
    lc = estate.groupby(["db_engine", "major_version", "lifecycle_status"]).size().reset_index(name="instances")
    lc["version"] = lc["major_version"].str.replace("SQL Server ", "SQL ")
    fig = px.bar(lc, x="version", y="instances", color="lifecycle_status", facet_col="db_engine", color_discrete_map=PALETTE,
                 title="Version & vendor support status",
                 category_orders={"lifecycle_status": ["Unsupported", "Approaching EOS", "Extended Support", "Supported"]})
    fig.update_xaxes(matches=None, title="", tickangle=-45)
    fig.for_each_annotation(lambda x: x.update(text=x.text.split("=")[-1]))
    fig.update_layout(height=400, margin=dict(t=60, b=10, l=10, r=10), legend_title="", legend=LEG)
    chart(fig)
with r:
    tl = estate.dropna(subset=["support_end"]).copy()
    tl["support_end"] = pd.to_datetime(tl["support_end"])
    tl = tl.groupby(["support_end", "major_version", "db_engine"]).size().reset_index(name="instances")
    fig = px.scatter(tl, x="support_end", y="major_version", size="instances", color="db_engine", color_discrete_map=PALETTE,
                     title="End-of-support timeline", size_max=30)
    fig.add_vline(x=pd.Timestamp(config.ASSESSMENT_DATE).timestamp() * 1000, line_dash="dash", line_color=C["red"],
                  annotation_text="Today", annotation_position="top")
    fig.update_layout(height=400, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="", xaxis_title="", legend_title="", legend=LEG)
    chart(fig)

# ------------------------------------------------------------------ Charts row 3 - money
l, r = st.columns([1.2, 1])
with l:
    fig = px.bar(a.levers, x="annual_saving", y="lever", color="evidence_class", orientation="h",
                 color_discrete_map={"Proposed": C["green"], "Potential (evidence gap)": C["amber"], "Validated (approved)": C["teal"]},
                 title="Annual savings by lever")
    fig.update_layout(height=380, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="", xaxis_title="£ per year", legend_title="",
                      yaxis={"categoryorder": "total ascending"}, legend=LEG)
    chart(fig)
with r:
    curve = a.tco_curve
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve.year, y=curve.current_cumulative, name="Current state", line=dict(color=C["muted"], width=3)))
    fig.add_trace(go.Scatter(x=curve.year, y=curve.target_cumulative, name="Target state (incl. one-time)", line=dict(color=C["green"], width=3)))
    fig.add_trace(go.Bar(x=curve.year, y=curve.net_benefit, name="Cumulative net benefit", marker_color=C["sky"], opacity=0.6))
    fig.update_layout(title="5-year cumulative TCO", height=380, margin=dict(t=50, b=10, l=10, r=10),
                      xaxis_title="Year", yaxis_title="£", legend=LEG)
    chart(fig)

# ------------------------------------------------------------------ Charts row 4 - risk & licence
l, r = st.columns([1, 1.1])
with l:
    cats = ["risk_lifecycle", "risk_availability", "risk_recoverability", "risk_security", "risk_licence", "risk_evidence"]
    short = {"Payments & Checkout": "PAY", "Supply Chain & Inventory": "SCM", "Unassigned": "N/A"}
    hm = estate.assign(service=estate.business_service.map(service_name).map(short)).groupby(["service", "db_engine"])[cats].mean().round(0)
    hm.index = [f"{s}<br>{'ORA' if e == 'Oracle' else 'SQL'}" for s, e in hm.index]
    hm.columns = [c.replace("risk_", "").title() for c in cats]
    fig = px.imshow(hm.T, text_auto=True, color_continuous_scale=HEAT_RED, aspect="auto",
                    title="Risk heatmap (avg score 0-100)")
    fig.update_layout(height=380, margin=dict(t=50, b=10, l=10, r=10), coloraxis_showscale=False)
    fig.update_xaxes(side="bottom", title="PAY = Payments · SCM = Supply chain · N/A = no owner", tickangle=0)
    chart(fig)
with r:
    lp = a.licence_position[a.licence_position.delta != 0].sort_values("delta").copy()
    lp["position"] = lp.status.map(lambda s: "Surplus" if s.startswith("Surplus") else "Potential shortfall (validate)")
    fig = px.bar(lp, x="delta", y="product", orientation="h", color="position",
                 color_discrete_map={"Surplus": C["green"], "Potential shortfall (validate)": C["red"]},
                 title="Licence position: entitled − deployed", hover_data=["entitled", "deployed_requirement", "metric", "status"])
    fig.update_layout(height=380, margin=dict(t=50, b=10, l=10, r=10), yaxis_title="", xaxis_title="units (indicative)",
                      legend=LEG, legend_title="")
    chart(fig)

# ------------------------------------------------------------------ Tables
l, r = st.columns(2)
with l:
    st.markdown("##### 💷 Top 10 value opportunities")
    top = estate[estate.recommended_action != "Retain"].merge(a.recs[["instance_id", "net_5yr"]], on="instance_id") \
        .sort_values("net_5yr", ascending=False).head(10)
    st.dataframe(top[["instance_id", "db_engine", "recommended_action", "target_platform", "readiness", "annual_saving", "net_5yr"]],
                 hide_index=True, width="stretch",
                 column_config={"annual_saving": money_col("saving/yr"), "net_5yr": money_col("5-yr net")})
with r:
    st.markdown("##### 🚨 Top 10 risks needing attention")
    tr = estate.sort_values("risk_score", ascending=False).head(10)
    st.dataframe(tr[["instance_id", "db_engine", "environment", "risk_band", "risk_score", "risk_reasons"]], hide_index=True,
                 width="stretch", column_config={"risk_score": st.column_config.ProgressColumn("risk", min_value=0, max_value=100, format="%.0f")})

# ------------------------------------------------------------------ Insights
st.markdown("#### 💡 Key insights")
st.caption("Generated deterministically from the evidence - no AI involved.")
ins = []
esu = cost_rows[cost_rows.cost_type == "extended_security_updates"].annual_cost_gbp.sum()
if esu:
    ins.append(f"<b>{gbp(esu)}/yr</b> is spent on SQL Server Extended Security Updates for unsupported versions - upgrade or Azure "
               "(free ESUs on Azure VMs / evergreen PaaS) removes this premium.")
sql16 = estate[estate.major_version == "SQL Server 2016"]
if len(sql16):
    ins.append(f"<b>{len(sql16)}</b> SQL Server 2016 instances fell out of extended support on 14 Jul 2026.")
ee_fit = a.findings[(a.findings.category == "Edition optimisation") & a.findings.instance_id.isin(estate.instance_id)]
if len(ee_fit):
    ins.append(f"<b>{len(ee_fit)}</b> Enterprise-edition databases use no Enterprise-only features - edition right-sizing worth "
               f"<b>{gbp(ee_fit.est_annual_value_gbp.sum())}/yr</b> in support (subject to SME validation).")
vm = a.findings[(a.findings.category == "Virtualisation exposure") & a.findings.instance_id.isin(estate.instance_id)]
if len(vm):
    ins.append(f"<b>{len(vm)}</b> Oracle EE databases on VMware carry soft-partitioning exposure - flagged for licensing SME review, not a compliance finding.")
gaps = estate[estate.readiness == "Blocked"]
if len(gaps):
    ins.append(f"<b>{len(gaps)}</b> recommendations are blocked by missing dependency or RPO/RTO evidence - the engine refuses to mark them ready.")
surplus = a.licence_position.surplus_support_gbp.sum()
if surplus:
    top_s = a.licence_position.sort_values("surplus_support_gbp", ascending=False).iloc[0]
    ins.append(f"Shelfware: <b>{gbp(surplus)}/yr</b> support on surplus entitlements (largest: {top_s['product']}, "
               f"{int(top_s['delta'])} units) - review before renewal {top_s['renewal_date']}.")
for t in ins:
    st.markdown(f"<div class='insight'>{t}</div>", unsafe_allow_html=True)
