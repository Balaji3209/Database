"""Page 4 - AI Decision Assistant (Explore / Challenge / Verify / Own) and executive reports."""
import json

import streamlit as st

from dboptima import ai_advisor, config, database, reports
from dboptima.ui import apply_filters, get_analysis, hero, scenario

a = get_analysis()
sc = scenario()

hero("AI Assistant & Reports",
     "Rules-first, AI-assisted: deterministic facts → masked fact pack → Azure OpenAI explains & challenges → numbers verified → humans decide")

if sc.ai_privacy_strict:
    mode, tone = "🔒 Privacy mode - AI layer blocked. Rules-based explanations only; no data leaves the application.", "warning"
elif config.azure_openai_configured():
    mode, tone = f"🟢 Azure OpenAI connected (deployment `{config.AZURE_OPENAI_DEPLOYMENT}`). Only masked fact packs are sent.", "success"
else:
    mode, tone = "⚪ Azure OpenAI not configured - using rules-based fallback. Add credentials to `.env` to enable.", "info"
getattr(st, tone)(mode)

t1, t2, t3 = st.tabs(["🤖 Decision assistant", "📑 Executive reports", "🧾 Audit trail"])

# =============================================================== Assistant
with t1:
    ids = apply_filters(a.recs).instance_id.tolist()
    c = st.columns([1, 1.2, 2])
    scope = c[0].radio("Scope", ["Portfolio", "Single database"], horizontal=True, key="ai_scope")
    iid = c[1].selectbox("Database", ids, index=ids.index("ORA-0006") if "ORA-0006" in ids else 0, key="ai_iid",
                         disabled=scope == "Portfolio") if ids else None
    target = iid if scope == "Single database" else None
    c[2].markdown("**Four-stage reasoning** · Explore alternatives → Challenge assumptions → Verify against evidence → "
                  "Own (decision brief for humans)")
    b = st.columns(4)
    stage_clicked = None
    for col, stage, icon in zip(b, ai_advisor.STAGE_PROMPTS, ["🔭", "🥊", "🔍", "🧑‍⚖️"]):
        if col.button(f"{icon} {stage}", width="stretch", key=f"stage_{stage}"):
            stage_clicked = stage

    if "ai_history" not in st.session_state:
        st.session_state.ai_history = []
    question = st.chat_input("Ask about the estate, e.g. 'Which Oracle databases are blocked and why?' or 'Explain MSS-0001'")
    prompt = None
    if stage_clicked:
        prompt = ai_advisor.STAGE_PROMPTS[stage_clicked]
    elif question:
        prompt = question
    if prompt:
        with st.spinner("Assembling fact pack and generating answer..."):
            res = ai_advisor.advise(a, prompt, target, sc.ai_privacy_strict)
        st.session_state.ai_history.insert(0, dict(prompt=prompt if not stage_clicked else f"{stage_clicked} ({target or 'portfolio'})",
                                                   scope=target or "Portfolio", **res))

    with st.expander("Suggested questions"):
        st.markdown("- Which databases are unsupported and what is the plan?\n- Where is the licence optimisation coming from?\n"
                    "- What evidence is missing before we can migrate?\n- What happens if the budget is cut by 20%?\n"
                    "- Which databases are Azure candidates?\n- Explain ORA-0004\n- What are the highest risks?")

    for k, h in enumerate(st.session_state.ai_history[:6]):
        with st.container(border=True):
            st.markdown(f"**🗨️ {h['prompt']}**  \n<small>{h['mode']} · scope {h['scope']} · {h['at']}</small>", unsafe_allow_html=True)
            if h["error"]:
                st.caption(f"AI error (fell back to rules): {h['error'][:200]}")
            st.markdown(h["answer"])
            v = h["verification"]
            cc = st.columns([1, 1])
            with cc[0]:
                if len(v):
                    bad = v[~v.traced_to_fact_pack]
                    if len(bad):
                        st.warning(f"Verify: {len(bad)} of {len(v)} figures could not be traced to the fact pack - treat as unverified.")
                    else:
                        st.success(f"Verify: all {len(v)} figures traced to deterministic facts.")
                    with st.popover("Number check"):
                        st.dataframe(v, hide_index=True)
            with cc[1]:
                if h["masked_prompt"]:
                    with st.popover("What was sent to the AI (masked)"):
                        st.code(h["masked_prompt"][:6000], language="json")
    if st.session_state.ai_history and st.button("Clear conversation"):
        st.session_state.ai_history = []
        st.rerun()

    with st.expander("🔐 Privacy controls - masking preview"):
        masker = ai_advisor.Masker(a.data["database_instances"])
        sample = ai_advisor.instance_facts(a, iid or "ORA-0001")["instance"]
        l, r = st.columns(2)
        l.markdown("**Inside the application**")
        l.json({k: sample[k] for k in ("hostname", "instance_name", "database_name", "owner", "major_version", "edition")})
        r.markdown("**Sent to Azure OpenAI**")
        r.json(json.loads(masker.mask(json.dumps({k: sample[k] for k in ("hostname", "instance_name", "database_name", "owner",
                                                                         "major_version", "edition")}))))
        st.caption("Hostnames, instance & database names and people are pseudonymised; emails redacted; responses are un-masked locally. "
                   "Prompts are logged by hash only. Privacy mode blocks the AI layer entirely.")

# =============================================================== Reports
with t2:
    st.markdown("Decision packs contain: database information · problem identified · supporting evidence · recommended action · "
                "alternatives · cost comparison · risk · confidence · assumptions · human approval requirements.")
    c = st.columns(3)
    with c[0]:
        with st.container(border=True):
            st.markdown("#### 📊 Full decision pack (Excel)")
            st.caption("15 sheets: success measures, recommendations, option scores, evidence, risk, licence position & findings, "
                       "reconciliation exceptions, savings levers, TCO, budget scenario, waves, decision audit.")
            st.download_button("⬇️ Download Excel", reports.excel_decision_pack(a), "DB-OPTIMA_decision_pack.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch", type="primary")
    with c[1]:
        with st.container(border=True):
            st.markdown("#### 🧾 Executive summary (HTML)")
            st.caption("One-page board summary: KPIs, success measures, action mix, top opportunities, budget scenario. Print to PDF from the browser.")
            st.download_button("⬇️ Download executive summary", reports.html_executive_pack(a).encode("utf-8"),
                               "DB-OPTIMA_executive_summary.html", "text/html", width="stretch")
    with c[2]:
        with st.container(border=True):
            st.markdown("#### 🗄️ Database decision pack (HTML)")
            pick = st.selectbox("Database", a.recs.instance_id.tolist(), key="rep_iid")
            st.download_button("⬇️ Download decision pack", reports.html_instance_pack(a, pick).encode("utf-8"),
                               f"DB-OPTIMA_{pick}_decision_pack.html", "text/html", width="stretch")
    st.markdown("#### Preview - executive summary")
    st.markdown(ai_advisor.executive_summary(a))

# =============================================================== Audit
with t3:
    log = database.decision_log()
    st.markdown(f"**Human decision audit trail** - {len(log)} decision(s) recorded. AI never approves; every decision has a named owner.")
    if log.empty:
        st.info("No decisions recorded yet - use *Modernization & TCO → Decision advisor* to approve, reject or defer a recommendation.")
    else:
        st.dataframe(log, hide_index=True, width="stretch")
        st.download_button("⬇️ Export audit log (CSV)", log.to_csv(index=False).encode(), "decision_audit.csv", "text/csv")
    st.markdown("**Responsible-AI & security controls**")
    st.markdown("- Synthetic data only; every record carries `data_label = SYNTHETIC-DEMO`\n"
                "- Discovery designed for read-only accounts (`SELECT_CATALOG_ROLE` / `VIEW SERVER STATE`), no write privileges\n"
                "- Secrets from `.env` locally, Azure Key Vault in App Service; Microsoft Entra ID for sign-in in production\n"
                "- Sensitive identifiers masked before any AI call; privacy mode disables the AI layer\n"
                "- AI output numbers verified against deterministic facts; licence compliance is never declared\n"
                "- No migration is executed automatically - approved items hand over to change management")
