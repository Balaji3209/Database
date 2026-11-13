"""Module 8 - Executive decision reports (Excel decision pack + HTML decision briefs)."""
from __future__ import annotations

import html
import io
from datetime import datetime

import pandas as pd

from . import config, database
from .ai_advisor import executive_summary, instance_facts

DISCLAIMER = ("SYNTHETIC DEMO DATA. Figures use illustrative list prices and stated assumptions. Licence positions are "
              "indicative and not compliance determinations. All architecture, licensing and production decisions "
              "require named human approval.")


def excel_decision_pack(a) -> bytes:
    buf = io.BytesIO()
    kpi = pd.DataFrame([{"measure": v["name"], "target": v["target"], "actual": v["actual"], "met": v["met"], "detail": v["detail"]}
                        for v in a.kpis.values()])
    summary = pd.DataFrame([{"item": k, "value": v} for k, v in a.tco.items()] +
                           [{"item": f"licence_{k}", "value": v} for k, v in a.licence_opt.items()])
    sheets = {
        "README": pd.DataFrame({"DB-OPTIMA AI decision pack": [DISCLAIMER, f"Generated {datetime.now():%Y-%m-%d %H:%M}",
                                                               f"Assessment date {config.ASSESSMENT_DATE}",
                                                               f"Scenario {a.scenario.__dict__}"]}),
        "Success Measures": kpi,
        "Financial Summary": summary,
        "Recommendations": a.recs,
        "Option Scores": a.options,
        "Evidence": a.evidence,
        "Risk": a.risk,
        "Licence Position": a.licence_position,
        "Licence Findings": a.findings,
        "Reconciliation Exceptions": a.recon["exceptions"],
        "Savings by Lever": a.levers,
        "TCO Curve": a.tco_curve,
        "Budget Scenario": a.budget["programme"],
        "Migration Waves": a.waves[["instance_id", "recommended_action", "target_platform", "readiness", "wave", "move_group",
                                    "annual_saving", "one_time_cost"]],
        "Decision Audit": database.decision_log(),
    }
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for col in ws.columns:
                width = min(60, max(10, *(len(str(c.value or "")) for c in col[:50])))
                ws.column_dimensions[col[0].column_letter].width = width
            ws.freeze_panes = "A2"
    return buf.getvalue()


_CSS = """body{font-family:Segoe UI,Arial,sans-serif;margin:32px;color:#1f2937} h1{color:#0b3d91;margin-bottom:0}
.sub{color:#6b7280} .banner{background:#fff4e5;border-left:5px solid #f59e0b;padding:10px 14px;margin:16px 0;font-size:13px}
table{border-collapse:collapse;width:100%;margin:8px 0 18px;font-size:13px} th,td{border:1px solid #e5e7eb;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f3f4f6} h2{color:#0b3d91;border-bottom:2px solid #e5e7eb;padding-bottom:4px;margin-top:26px}
.badge{display:inline-block;padding:3px 10px;border-radius:12px;font-weight:600;color:#fff}
.Ready{background:#16a34a}.Conditional{background:#d97706}.Blocked{background:#dc2626}
.sig td{height:34px}"""


def _table(rows: list[dict] | pd.DataFrame) -> str:
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    return df.to_html(index=False, escape=True, border=0)


def html_instance_pack(a, iid: str) -> str:
    f = instance_facts(a, iid)
    i, rec, risk = f["instance"], f["recommendation"], f["risk"]
    e = html.escape
    opts = pd.DataFrame(f["options"]).sort_values("score", ascending=False)
    cost = opts[["option", "status", "target_platform", "annual_saving", "one_time_cost"]].copy()
    cost["5yr_net"] = 5 * cost.annual_saving - cost.one_time_cost
    for c in ("annual_saving", "one_time_cost", "5yr_net"):
        cost[c] = cost[c].map(lambda v: f"£{v:,.0f}")
    problem = risk["reasons"] or "No material risk - assessed for cost optimisation."
    body = f"""
<h1>Database Decision Pack - {e(iid)}</h1><div class='sub'>DB-OPTIMA AI | assessment {config.ASSESSMENT_DATE} | generated {datetime.now():%Y-%m-%d %H:%M}</div>
<div class='banner'>{e(DISCLAIMER)}</div>
<h2>1. Database information</h2>{_table([{k: v for k, v in i.items()}])}
<h2>2. Problem identified</h2><p>{e(problem)}</p>
<h2>3. Supporting evidence</h2>{_table(f['evidence'])}
<h2>4. Recommended action</h2><p><b>{e(rec['recommended_action'])}</b> &rarr; {e(str(rec['target_platform']))}
&nbsp;<span class='badge {e(rec['readiness'])}'>{e(rec['readiness'])}</span></p><p>{e(str(rec['rationale']))}</p>
<p><b>Next action:</b> {e(str(rec['next_action']))}</p>
<h2>5. Alternative options</h2>{_table(opts[['option', 'status', 'score', 'drivers', 'constraints', 'conditions']])}
<h2>6. Cost comparison</h2>{_table(cost)}
<h2>7. Risk assessment</h2><p>Risk band <b>{e(risk['risk_band'])}</b> (score {risk['risk_score']}); lifecycle {e(risk['lifecycle_status'])}, support end {e(risk['support_end'])}.</p>
<h2>8. Confidence level</h2><p><b>{e(rec['confidence'])}</b> ({rec['confidence_pct']}%) - weighted by evidence quality across inventory, workload, features, dependencies, recovery and cost.</p>
<h2>9. Assumptions</h2><ul>{''.join(f'<li>{e(x)}</li>' for x in str(a.recs.set_index('instance_id').loc[iid, 'assumptions']).split(' | '))}</ul>
<h2>10. Human approval</h2><p>Required: <b>{e(rec['approval_required'])}</b>. Current status: <b>{e(rec['human_decision'])}</b>.</p>
<table class='sig'><tr><th>Role</th><th>Name</th><th>Decision</th><th>Date</th></tr>
<tr><td>Enterprise / Database Architect</td><td></td><td></td><td></td></tr><tr><td>Licensing SME</td><td></td><td></td><td></td></tr>
<tr><td>Service Owner</td><td></td><td></td><td></td></tr></table>"""
    return f"<html><head><meta charset='utf-8'><title>{e(iid)} decision pack</title><style>{_CSS}</style></head><body>{body}</body></html>"


def _md_to_html(text: str) -> str:
    """Minimal markdown (### headings, '- ' bullets, **bold**) for our own deterministic summaries."""
    import re

    out, in_list = [], False
    for line in text.splitlines():
        s = html.escape(line.strip())
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        if s.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{s[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if s.startswith("### "):
            out.append(f"<h2>{s[4:]}</h2>")
        elif s:
            out.append(f"<p>{s}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def html_executive_pack(a) -> str:
    kpi = pd.DataFrame([{"Success measure": v["name"], "Target": v["target"], "Actual": f"{v['actual']}%",
                         "Status": "Met" if v["met"] else "Not met", "Detail": v["detail"]} for v in a.kpis.values()])
    top = a.recs.sort_values("net_5yr", ascending=False).head(15)[
        ["instance_id", "recommended_action", "target_platform", "readiness", "confidence", "annual_saving", "one_time_cost", "net_5yr"]].copy()
    for c in ("annual_saving", "one_time_cost", "net_5yr"):
        top[c] = top[c].map(lambda v: f"£{v:,.0f}")
    mix = a.recs.pivot_table(index="recommended_action", columns="readiness", values="instance_id", aggfunc="count", fill_value=0)
    body = f"""<h1>DB-OPTIMA AI - Executive Decision Summary</h1>
<div class='sub'>Assessment {config.ASSESSMENT_DATE} | generated {datetime.now():%Y-%m-%d %H:%M}</div>
<div class='banner'>{html.escape(DISCLAIMER)}</div>
{_md_to_html(executive_summary(a))}
<h2>Success measures</h2>{_table(kpi)}
<h2>Recommendation mix by readiness</h2>{mix.to_html(border=0)}
<h2>Top 15 opportunities</h2>{_table(top)}
<h2>Budget scenario (-{a.scenario.budget_cut_pct or 20:.0f}%)</h2>
<p>Funded {a.budget['funded_count']} items, deferred {a.budget['deferred_count']}; mandatory risk items funded
{a.budget['mandatory_funded']}/{a.budget['mandatory_total']}; recurring savings retained {a.budget['saving_retained_pct']}%.</p>"""
    return f"<html><head><meta charset='utf-8'><title>DB-OPTIMA executive summary</title><style>{_CSS}</style></head><body>{body}</body></html>"
