"""Shared Streamlit UI helpers: dark theme, cached analysis, sidebar scenarios/filters, KPI cards, charts."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from . import config
from .pipeline import Analysis, Scenario, run

# ---------------------------------------------------------------------------------------------
# "Midnight Aurora" dark palette - deep navy surfaces, sky/violet accents, soft semantic colours
# ---------------------------------------------------------------------------------------------
C = {
    "bg": "#0B1120", "surface": "#131B2E", "surface2": "#16213A", "border": "#1F2A44", "grid": "#1E293B",
    "text": "#E2E8F0", "muted": "#94A3B8", "dim": "#64748B",
    "sky": "#38BDF8", "violet": "#A78BFA", "indigo": "#818CF8", "teal": "#2DD4BF", "pink": "#F472B6",
    "green": "#34D399", "amber": "#FBBF24", "orange": "#FB923C", "red": "#F87171", "rose": "#F43F5E",
    "slate": "#64748B", "track": "#334155",
}
COLORWAY = [C["sky"], C["violet"], C["green"], C["amber"], C["pink"], C["orange"], C["teal"], C["indigo"], C["red"], C["muted"]]
HEAT_RED = [[0, "#111827"], [0.35, "#7F1D1D"], [0.7, "#DC2626"], [1, "#F43F5E"]]
HEAT_BLUE = [[0, "#0F172A"], [0.5, "#0369A1"], [1, "#38BDF8"]]

PALETTE = {"Retain": C["slate"], "Upgrade": C["indigo"], "Consolidate": C["violet"], "Replatform": C["teal"],
           "Cloud Migrate": C["sky"], "Retire": C["green"],
           "Ready": C["green"], "Conditional": C["amber"], "Blocked": C["red"],
           "Unsupported": C["red"], "Approaching EOS": C["orange"], "Extended Support": C["amber"], "Supported": C["green"],
           "Critical": C["rose"], "High": C["red"], "Medium": C["amber"], "Low": C["green"],
           "Oracle": C["orange"], "SQL Server": "#60A5FA"}

_template = go.layout.Template(pio.templates["plotly_dark"])
_template.layout.update(
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", colorway=COLORWAY,
    font=dict(family="Inter, Segoe UI, sans-serif", color=C["text"], size=12),
    title=dict(font=dict(size=15, color="#F1F5F9")),
    xaxis=dict(gridcolor=C["grid"], zerolinecolor=C["track"], linecolor=C["border"], tickcolor=C["border"]),
    yaxis=dict(gridcolor=C["grid"], zerolinecolor=C["track"], linecolor=C["border"], tickcolor=C["border"]),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=C["muted"])),
    hoverlabel=dict(bgcolor=C["surface2"], bordercolor=C["border"], font=dict(color=C["text"])),
    polar=dict(bgcolor="rgba(0,0,0,0)", radialaxis=dict(gridcolor=C["grid"], linecolor=C["border"]),
               angularaxis=dict(gridcolor=C["grid"], linecolor=C["border"])),
)
pio.templates["dboptima_dark"] = _template
pio.templates.default = "dboptima_dark"


def chart(fig: go.Figure) -> None:
    """Render a Plotly figure with the DB-OPTIMA dark template (Streamlit's own chart theme disabled)."""
    fig.update_layout(template="dboptima_dark")
    st.plotly_chart(fig, width="stretch", theme=None)


CSS = f"""
<style>
.block-container{{padding-top:1.2rem;padding-bottom:2rem;padding-left:1.5rem;padding-right:1.5rem;max-width:1600px}}
[data-testid="stSidebar"]{{background:linear-gradient(180deg,#0E1627 0%,#0B1120 100%);border-right:1px solid {C['border']}}}
[data-testid="stHeader"]{{background:rgba(11,17,32,.85);backdrop-filter:blur(6px)}}
h1,h2,h3,h4,h5{{color:#F1F5F9}}
.kpi{{background:linear-gradient(145deg,{C['surface']} 0%,#0F172A 100%);border:1px solid {C['border']};border-radius:14px;
     padding:14px 16px;box-shadow:0 4px 18px rgba(0,0,0,.35);height:100%}}
.kpi .label{{font-size:.74rem;color:{C['muted']};text-transform:uppercase;letter-spacing:.06em;font-weight:600}}
.kpi .value{{font-size:1.65rem;font-weight:700;color:#F8FAFC;line-height:1.25;margin-top:2px}}
.kpi .sub{{font-size:.8rem;color:{C['muted']};margin-top:2px}}
.kpi.red{{border-left:4px solid {C['red']};box-shadow:inset 6px 0 18px -10px {C['red']},0 4px 18px rgba(0,0,0,.35)}}
.kpi.amber{{border-left:4px solid {C['amber']};box-shadow:inset 6px 0 18px -10px {C['amber']},0 4px 18px rgba(0,0,0,.35)}}
.kpi.green{{border-left:4px solid {C['green']};box-shadow:inset 6px 0 18px -10px {C['green']},0 4px 18px rgba(0,0,0,.35)}}
.kpi.blue{{border-left:4px solid {C['sky']};box-shadow:inset 6px 0 18px -10px {C['sky']},0 4px 18px rgba(0,0,0,.35)}}
.hero{{background:radial-gradient(circle at 85% 20%,rgba(167,139,250,.35) 0%,transparent 45%),
      linear-gradient(110deg,#0F1B3D 0%,#1E3A8A 50%,#0E7490 100%);border:1px solid #23345C;
      color:#fff;border-radius:16px;padding:18px 24px;margin-bottom:14px;box-shadow:0 10px 30px rgba(2,6,23,.6)}}
.hero h1{{color:#fff;font-size:1.75rem;margin:0}}.hero p{{margin:4px 0 0;color:#BAE6FD;font-size:.95rem}}
.pill{{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.74rem;font-weight:600;margin-right:6px;border:1px solid}}
.pill.demo{{background:rgba(251,191,36,.12);color:#FCD34D;border-color:rgba(251,191,36,.45)}}
.pill.scn{{background:rgba(248,113,113,.12);color:#FCA5A5;border-color:rgba(248,113,113,.45)}}
.pill.ok{{background:rgba(52,211,153,.12);color:#6EE7B7;border-color:rgba(52,211,153,.45)}}
.sc-card{{border:1px solid {C['border']};border-radius:12px;padding:12px 14px;background:{C['surface']};height:100%}}
.sc-card .t{{font-size:.8rem;color:#CBD5E1;font-weight:600;min-height:2.3em}}.sc-card .v{{font-size:1.5rem;font-weight:700}}
.sc-card .d{{font-size:.75rem;color:{C['muted']}}}
.insight{{background:{C['surface']};border:1px solid {C['border']};border-left:4px solid {C['sky']};padding:8px 12px;
         border-radius:8px;margin-bottom:6px;font-size:.92rem;color:{C['text']}}}
.insight b{{color:#7DD3FC}}
div[data-testid="stMetricValue"]{{font-size:1.4rem;color:#F8FAFC}}
div[data-testid="stMetric"]{{background:{C['surface']};border:1px solid {C['border']};border-radius:12px;padding:10px 12px}}
</style>
"""


@st.cache_resource(show_spinner="Running DB-OPTIMA intelligence services...")
def _analysis(oracle_down: bool, budget_cut: float, privacy: bool, _version: int) -> Analysis:
    return run(Scenario(oracle_discovery_unavailable=oracle_down, budget_cut_pct=budget_cut, ai_privacy_strict=privacy))


def refresh() -> None:
    st.session_state["_version"] = st.session_state.get("_version", 0) + 1


def scenario() -> Scenario:
    s = st.session_state
    return Scenario(oracle_discovery_unavailable=s.get("scn_oracle_down", False),
                    budget_cut_pct=float(s.get("scn_budget_cut", 20)) if s.get("scn_budget_on", False) else 0.0,
                    ai_privacy_strict=s.get("scn_privacy", False))


def get_analysis(baseline: bool = False) -> Analysis:
    sc = Scenario() if baseline else scenario()
    return _analysis(sc.oracle_discovery_unavailable, sc.budget_cut_pct, sc.ai_privacy_strict, st.session_state.get("_version", 0))


def sidebar() -> None:
    with st.sidebar:
        st.markdown("## 🧭 DB-OPTIMA AI")
        st.caption("AI Database Estate Modernization & Licence Optimization Advisor")
        st.markdown("<span class='pill demo'>SYNTHETIC DEMO DATA</span>", unsafe_allow_html=True)
        st.divider()
        st.markdown("**🎯 What-if scenarios**")
        st.toggle("Oracle discovery collector (OEM) unavailable", key="scn_oracle_down",
                  help="Simulates loss of a key discovery technology. Oracle evidence falls back to last-known snapshot.")
        st.toggle("Transformation budget reduced", key="scn_budget_on", help="Re-prioritises the programme under a budget cut.")
        if st.session_state.get("scn_budget_on"):
            st.slider("Budget reduction %", 5, 40, 20, 5, key="scn_budget_cut")
        st.toggle("Privacy mode: block AI layer", key="scn_privacy",
                  help="Sensitive information is prohibited from reaching the AI layer - rules-based explanations only.")
        st.divider()
        st.markdown("**🔎 Filters**")
        st.multiselect("Business service", ["Payments & Checkout", "Supply Chain & Inventory", "Unassigned"], key="f_service")
        st.multiselect("Engine", ["Oracle", "SQL Server"], key="f_engine")
        st.multiselect("Environment", ["Production", "Pre-Production", "Test", "Development"], key="f_env")
        st.divider()
        ai = "🟢 Azure OpenAI configured" if config.azure_openai_configured() else "⚪ Azure OpenAI not configured (rules fallback)"
        if st.session_state.get("scn_privacy"):
            ai = "🔒 AI layer blocked (privacy mode)"
        st.caption(ai)
        st.caption(f"Assessment date: {config.ASSESSMENT_DATE:%d %b %Y}")


SERVICE_NAMES = {"BS-PAY": "Payments & Checkout", "BS-SCM": "Supply Chain & Inventory", "": "Unassigned"}


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    s = st.session_state
    out = df
    if "business_service" in out and s.get("f_service"):
        names = out["business_service"].map(lambda v: SERVICE_NAMES.get(v, v))
        out = out[names.isin(s["f_service"])]
    if "db_engine" in out and s.get("f_engine"):
        out = out[out["db_engine"].isin(s["f_engine"])]
    if "environment" in out and s.get("f_env"):
        out = out[out["environment"].isin(s["f_env"])]
    return out


def filters_active() -> bool:
    s = st.session_state
    return bool(s.get("f_service") or s.get("f_engine") or s.get("f_env"))


def hero(title: str, subtitle: str) -> None:
    sc = scenario()
    pills = "<span class='pill demo'>SYNTHETIC DEMO DATA</span>"
    if sc.oracle_discovery_unavailable:
        pills += "<span class='pill scn'>SCENARIO: Oracle discovery down</span>"
    if sc.budget_cut_pct:
        pills += f"<span class='pill scn'>SCENARIO: budget -{sc.budget_cut_pct:.0f}%</span>"
    if sc.ai_privacy_strict:
        pills += "<span class='pill scn'>SCENARIO: AI blocked</span>"
    if filters_active():
        pills += "<span class='pill ok'>Filters applied</span>"
    st.markdown(f"<div class='hero'><h1>{title}</h1><p>{subtitle}</p><div style='margin-top:8px'>{pills}</div></div>",
                unsafe_allow_html=True)


def kpi(col, label: str, value: str, sub: str = "", tone: str = "blue") -> None:
    col.markdown(_kpi_html(label, value, sub, tone), unsafe_allow_html=True)


def _kpi_html(label: str, value: str, sub: str = "", tone: str = "blue") -> str:
    return (f"<div class='kpi {tone}'><div class='label'>{label}</div><div class='value'>{value}</div>"
            f"<div class='sub'>{sub}</div></div>")


def kpi_grid(cards: list[tuple], min_width: int = 190) -> None:
    """Responsive KPI cards that reflow from 6 per row (wide screens) down to 1 (narrow)."""
    html = "".join(_kpi_html(*c) for c in cards)
    st.markdown(f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax({min_width}px,1fr));gap:12px'>{html}</div>",
                unsafe_allow_html=True)


def gbp(v: float, short: bool = True) -> str:
    if v is None or pd.isna(v):
        return "n/a"
    if short and abs(v) >= 1e6:
        return f"£{v / 1e6:,.2f}M"
    if short and abs(v) >= 1e4:
        return f"£{v / 1e3:,.0f}k"
    return f"£{v:,.0f}"


def money_col(label: str) -> st.column_config.NumberColumn:
    return st.column_config.NumberColumn(f"{label} (£)", format="localized")


def service_name(v: str) -> str:
    return SERVICE_NAMES.get(v, v)
