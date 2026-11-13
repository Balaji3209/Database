"""Module 7 - AI decision assistant (Azure OpenAI) with privacy masking and rules-based fallback.

Principles
- Deterministic Python produces every fact, score and figure; the LLM only explains and challenges.
- Only a masked "fact pack" is sent to the AI layer (no hostnames, instance/database names or people).
- Every numeric value in an AI answer is VERIFIED against the fact pack; unverified numbers are flagged.
- Humans own the decision (Explore -> Challenge -> Verify -> Own).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

import pandas as pd

from . import config
from .config import get_logger

log = get_logger("ai_advisor")

SYSTEM_PROMPT = """You are DB-OPTIMA AI, an advisory assistant for database estate modernization and licence optimisation.
Rules you must follow:
1. Use ONLY the facts in the provided FACT PACK. Never invent figures, versions, dates or prices.
2. If information is missing, say exactly what evidence is missing and who should provide it.
3. Never declare legal licence compliance or non-compliance; describe indicative positions needing SME validation.
4. Recommendations are decision support only - architecture, licensing and production decisions are owned by humans.
5. Be concise, structured (headings + bullets) and suitable for senior architects and executives. Use GBP (£)."""

STAGE_PROMPTS = {
    "Explore": "EXPLORE: Generate the realistic alternatives for this decision, the hypotheses behind each, and what would make each one win.",
    "Challenge": "CHALLENGE: Act as a sceptical review board. Identify weak assumptions, missing evidence, optimistic figures and risks that could invalidate the recommendation.",
    "Verify": "VERIFY: Check the recommendation against the facts. List each claim, the supporting fact, and whether it is verified, assumed or unsupported.",
    "Own": "OWN: Prepare a one-page decision brief for the human approvers: decision requested, options, recommendation, conditions, approvers and what they must confirm.",
}


class Masker:
    """Reversible pseudonymisation of sensitive identifiers before anything reaches the AI layer."""

    EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

    def __init__(self, instances: pd.DataFrame):
        self.forward: dict[str, str] = {}
        for col, prefix in (("hostname", "HOST"), ("instance_name", "INST"), ("database_name", "DBNAME"), ("owner", "PERSON")):
            for k, val in enumerate(sorted({v for v in instances[col].astype(str) if v and v != "MSSQLSERVER"}), start=1):
                self.forward.setdefault(val, f"<{prefix}_{k:03d}>")
        self._pattern = re.compile("|".join(re.escape(k) for k in sorted(self.forward, key=len, reverse=True))) if self.forward else None
        self.reverse = {v: k for k, v in self.forward.items()}

    def mask(self, text: str) -> str:
        if self._pattern:
            text = self._pattern.sub(lambda m: self.forward[m.group(0)], text)
        return self.EMAIL.sub("<EMAIL>", text)

    def unmask(self, text: str) -> str:
        for token, val in self.reverse.items():
            text = text.replace(token, val)
        return text


def _round(v):
    if isinstance(v, float):
        return round(v, 1)
    return v


def portfolio_facts(a) -> dict:
    recs = a.recs
    return {
        "data_label": config.SYNTHETIC_LABEL,
        "assessment_date": config.ASSESSMENT_DATE.isoformat(),
        "scenario": a.scenario.__dict__,
        "estate": {"instances": int(len(recs)), "by_engine": recs.db_engine.value_counts().to_dict(),
                   "by_environment": recs.environment.value_counts().to_dict(),
                   "lifecycle": a.risk.lifecycle_status.value_counts().to_dict(),
                   "risk_bands": a.risk.risk_band.value_counts().to_dict(),
                   "high_or_critical_risk": int(a.risk.risk_band.isin(["Critical", "High"]).sum())},
        "recommendations": {"by_action": recs.recommended_action.value_counts().to_dict(),
                            "by_readiness": recs.readiness.value_counts().to_dict(),
                            "by_confidence": recs.confidence.value_counts().to_dict()},
        "financials_gbp": {k: _round(float(v)) if v is not None else None for k, v in a.tco.items()},
        "licence_optimisation_gbp": {k: _round(float(v)) for k, v in a.licence_opt.items()},
        "success_measures": {k: {"target": v["target"], "actual": v["actual"], "met": bool(v["met"]), "detail": v["detail"]}
                             for k, v in a.kpis.items()},
        "reconciliation": {k: (int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer() else v)
                           for k, v in a.recon["summary"].items()},
        "top_opportunities": recs.sort_values("net_5yr", ascending=False).head(10)[
            ["instance_id", "recommended_action", "target_platform", "readiness", "annual_saving", "one_time_cost", "net_5yr"]
        ].round(0).to_dict("records"),
        "blocked": recs[recs.readiness == "Blocked"][["instance_id", "recommended_action", "constraints"]].to_dict("records"),
        "lifecycle_by_version": {f"{k[0]} | {k[1]}": int(v) for k, v in a.risk.merge(
            a.data["database_instances"][["instance_id", "major_version"]], on="instance_id")
            .groupby(["major_version", "lifecycle_status"]).size().items()},
        "licence_position": a.licence_position[["product", "entitled", "deployed_requirement", "delta", "status",
                                                "surplus_support_gbp"]].to_dict("records"),
        "highest_risks": a.risk.sort_values("risk_score", ascending=False).head(10)[
            ["instance_id", "risk_band", "risk_score", "risk_reasons"]].to_dict("records"),
        "azure_targets": recs[recs.recommended_action == "Cloud Migrate"].target_platform
            .str.replace(r" \(.*\)$", "", regex=True).value_counts().to_dict(),
        "budget_scenario": {k: _round(float(v)) for k, v in a.budget.items() if k != "programme"},
    }


def instance_facts(a, iid: str) -> dict:
    inst = a.data["database_instances"].set_index("instance_id").loc[iid]
    rec = a.recs.set_index("instance_id").loc[iid]
    risk = a.risk.set_index("instance_id").loc[iid]
    opts = a.options[a.options.instance_id == iid]
    ev = a.evidence[a.evidence.instance_id == iid]
    w = a.data["workload_metrics"].set_index("instance_id").loc[iid]
    r = a.data["recovery_requirements"].set_index("instance_id").loc[iid]
    return {
        "data_label": config.SYNTHETIC_LABEL,
        "instance": {k: _round(inst[k].item() if hasattr(inst[k], "item") else inst[k]) for k in [
            "db_engine", "hostname", "instance_name", "database_name", "major_version", "version_build", "edition",
            "environment", "business_service", "application_id", "owner", "server_type", "os_platform", "physical_cores",
            "vcpus", "memory_gb", "db_size_gb", "cluster_type", "ha_dr_config", "code_objects", "db_links_or_linked_servers",
            "data_classification", "data_residency"]},
        "workload": {"cpu_p95_pct": float(w.cpu_p95_pct), "memory_used_pct": float(w.memory_used_pct),
                     "connections_90d": int(w.connections_90d), "last_connection_date": w.last_connection_date},
        "recovery": {"tier": r.criticality_tier, "rpo_minutes": None if pd.isna(r.rpo_minutes) else float(r.rpo_minutes),
                     "rto_minutes": None if pd.isna(r.rto_minutes) else float(r.rto_minutes)},
        "risk": {"lifecycle_status": risk.lifecycle_status, "support_end": str(risk.support_end), "risk_score": float(risk.risk_score),
                 "risk_band": risk.risk_band, "reasons": risk.risk_reasons},
        "recommendation": {k: _round(rec[k].item() if hasattr(rec[k], "item") else rec[k]) for k in [
            "recommended_action", "target_platform", "readiness", "score", "runner_up", "runner_up_score", "current_annual",
            "target_annual", "annual_saving", "one_time_cost", "payback_months", "net_5yr", "confidence", "confidence_pct",
            "rationale", "constraints", "conditions", "next_action", "human_decision", "approval_required"]},
        "options": opts[["option", "status", "score", "target_platform", "annual_saving", "one_time_cost", "drivers",
                         "constraints", "conditions"]].round(1).to_dict("records"),
        "evidence": ev[["evidence_type", "quality", "source", "fact"]].to_dict("records"),
    }


def _numbers(text: str) -> list[float]:
    vals = []
    pattern = r"(?<![\w<,.\-])(-)?£?\s?(-)?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?(?:(k|m|K|M)(?![A-Za-z]))?%?"
    for m in re.finditer(pattern, text):
        num = float(m.group(3).replace(",", ""))
        mult = {"k": 1e3, "m": 1e6}.get((m.group(4) or "").lower(), 1)
        sign = -1 if (m.group(1) or m.group(2)) else 1
        vals.append(sign * num * mult)
    return vals


def verify_numbers(answer: str, facts: dict) -> pd.DataFrame:
    """Flag any number in the AI answer that cannot be traced to the fact pack (+-1.5% tolerance)."""
    fact_nums = set(_numbers(json.dumps(facts, default=str, ensure_ascii=False)))
    rows = []
    for n in sorted(set(_numbers(answer))):
        if abs(n) < 10 or 1900 <= n <= 2100:  # ignore small counts/years - too ambiguous to verify
            continue
        ok = any(abs(abs(n) - abs(f)) <= max(1.0, 0.015 * abs(f)) for f in fact_nums)
        rows.append({"value_in_answer": n, "traced_to_fact_pack": ok})
    return pd.DataFrame(rows)


def call_azure_openai(stage_or_question: str, facts: dict, masker: Masker) -> tuple[str, str]:
    """Returns (answer, masked_prompt). Raises on failure so callers can fall back."""
    from openai import AzureOpenAI

    fact_text = masker.mask(json.dumps(facts, default=str, indent=1, ensure_ascii=False))
    user = f"FACT PACK (masked, synthetic):\n{fact_text}\n\nTASK:\n{masker.mask(stage_or_question)}"
    client = AzureOpenAI(azure_endpoint=config.AZURE_OPENAI_ENDPOINT, api_key=config.AZURE_OPENAI_API_KEY,
                         api_version=config.AZURE_OPENAI_API_VERSION, timeout=45)
    resp = client.chat.completions.create(
        model=config.AZURE_OPENAI_DEPLOYMENT, temperature=0.2, max_tokens=900,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}])
    answer = resp.choices[0].message.content or ""
    log.info("AI call ok | prompt_sha256=%s | chars=%d", hashlib.sha256(user.encode()).hexdigest()[:16], len(user))
    return masker.unmask(answer), user


def advise(a, prompt: str, instance_id: str | None, privacy_strict: bool) -> dict:
    """Single entry point used by the UI. Always returns an answer (AI or deterministic fallback)."""
    facts = instance_facts(a, instance_id) if instance_id else portfolio_facts(a)
    masker = Masker(a.data["database_instances"])
    mode, masked_prompt, error = "Rules-based fallback", "", ""
    if privacy_strict:
        mode = "Rules-based (privacy mode - AI layer blocked)"
    elif config.azure_openai_configured():
        try:
            answer, masked_prompt = call_azure_openai(prompt, facts, masker)
            mode = f"Azure OpenAI ({config.AZURE_OPENAI_DEPLOYMENT})"
            return dict(answer=answer, mode=mode, masked_prompt=masked_prompt, verification=verify_numbers(answer, facts),
                        error="", at=datetime.now().isoformat(timespec="seconds"))
        except Exception as exc:  # network, auth, content filter...
            error = f"{type(exc).__name__}: {exc}"
            log.warning("Azure OpenAI unavailable - falling back: %s", error)
            mode = "Rules-based fallback (AI call failed)"
    else:
        mode = "Rules-based fallback (Azure OpenAI not configured)"
    answer = fallback(a, prompt, instance_id)
    return dict(answer=answer, mode=mode, masked_prompt=masked_prompt, verification=verify_numbers(answer, facts),
                error=error, at=datetime.now().isoformat(timespec="seconds"))


# ------------------------------------------------------------------------------------------
# Deterministic fallback narratives
# ------------------------------------------------------------------------------------------
def explain_instance(a, iid: str, stage: str = "Explore") -> str:
    f = instance_facts(a, iid)
    i, rec, risk = f["instance"], f["recommendation"], f["risk"]
    opts = sorted(f["options"], key=lambda o: o["score"], reverse=True)
    lines = [f"### {iid} - {i['db_engine']} {i['major_version']} {i['edition']} ({i['environment']})",
             f"**Recommendation:** {rec['recommended_action']} -> {rec['target_platform']} | readiness **{rec['readiness']}** | "
             f"confidence **{rec['confidence']} ({rec['confidence_pct']}%)**"]
    if stage == "Explore":
        lines.append("**Alternatives considered (score / status):**")
        for o in opts:
            lines.append(f"- **{o['option']}** - {o['score']} / {o['status']}: {o['drivers'] or o['constraints']}")
    elif stage == "Challenge":
        lines.append("**Points a review board should challenge:**")
        weak = [e for e in f["evidence"] if e["quality"] not in ("High",)]
        for e in weak:
            lines.append(f"- {e['evidence_type']} evidence is **{e['quality']}** ({e['source']}) - confirm before approval")
        if rec["conditions"]:
            lines.append(f"- Open conditions: {rec['conditions']}")
        if rec["runner_up"] and rec["score"] - rec["runner_up_score"] < 5:
            lines.append(f"- Close call: runner-up **{rec['runner_up']}** scores {rec['runner_up_score']} vs {rec['score']}")
        lines.append("- Cost figures use illustrative list prices and rate-card assumptions - validate with Finance/Procurement")
        if not weak and not rec["conditions"]:
            lines.append("- Evidence quality is high; main residual risk is execution (testing, cut-over window)")
    elif stage == "Verify":
        lines.append("**Claim -> evidence trace:**")
        for e in f["evidence"]:
            lines.append(f"- {e['evidence_type']}: {e['fact']}  _(source: {e['source']}; quality {e['quality']})_")
    else:
        lines += ["**Decision requested:** approve / reject / defer the recommendation below.",
                  f"- Action: **{rec['recommended_action']}** to {rec['target_platform']}",
                  f"- Annual saving £{rec['annual_saving']:,.0f}; one-time £{rec['one_time_cost']:,.0f}; 5-yr net £{rec['net_5yr']:,.0f}",
                  f"- Conditions to confirm: {rec['conditions'] or 'none'}",
                  f"- Approvers: {rec['approval_required']}", f"- Current human decision: **{rec['human_decision']}**",
                  "- No production change is executed by DB-OPTIMA; approved items move to change management."]
    lines.append(f"**Risk:** {risk['risk_band']} ({risk['risk_score']}) - {risk['reasons'] or 'no material risks'}")
    return "\n".join(lines)


def executive_summary(a) -> str:
    t, lo, k = a.tco, a.licence_opt, a.kpis
    recs = a.recs
    unsup = int((a.risk.lifecycle_status == "Unsupported").sum())
    lines = [
        "### Executive summary (synthetic pilot estate)",
        f"- **Estate:** {len(recs)} database instances (Oracle {int((recs.db_engine == 'Oracle').sum())}, "
        f"SQL Server {int((recs.db_engine == 'SQL Server').sum())}) across 2 business services.",
        f"- **Risk:** {unsup} instances run unsupported versions; "
        f"{int(a.risk.risk_band.isin(['Critical', 'High']).sum())} are rated High/Critical risk.",
        f"- **Value:** recurring run-cost reduction of **£{t['annual_saving']:,.0f}/yr** for a one-time investment of "
        f"£{t['one_time']:,.0f} (payback {t['payback_months']} months, 5-yr net £{t['net_5yr']:,.0f}).",
        f"- **Licensing:** £{lo['proposed']:,.0f}/yr proposed licence & support optimisation "
        f"(**{lo['proposed_pct']}%** of £{lo['licence_support_spend']:,.0f}); further £{lo['potential']:,.0f} once conditions are cleared.",
        f"- **Readiness:** {k['migration_ready']['detail']}.",
        f"- **Evidence:** {k['reconciliation']['detail']}; every recommendation is traceable ({k['traceability']['actual']}%).",
        "- **Decision ask:** approve Wave 0 quick wins and Wave 1 risk remediation; fund evidence collection for blocked items.",
    ]
    return "\n".join(lines)


def fallback(a, prompt: str, instance_id: str | None) -> str:
    q = prompt.lower()
    for stage in STAGE_PROMPTS:
        if q.startswith(stage.lower()):
            return explain_instance(a, instance_id, stage) if instance_id else executive_summary(a)
    m = re.search(r"\b(ora|mss)-\d{4}\b", q)
    if m:
        return explain_instance(a, m.group(0).upper(), "Explore")
    if instance_id and any(w in q for w in ("why", "explain", "recommend")):
        return explain_instance(a, instance_id, "Explore")
    recs, risk = a.recs, a.risk
    if any(w in q for w in ("unsupported", "end of support", "eos", "lifecycle")):
        df = risk[risk.lifecycle_status.isin(["Unsupported", "Approaching EOS"])].merge(
            a.data["database_instances"][["instance_id", "major_version", "environment"]], on="instance_id")
        top = df.groupby(["major_version", "lifecycle_status"]).size().sort_values(ascending=False)
        return "### Lifecycle exposure\n" + "\n".join(f"- {v} x {k[0]} - {k[1]}" for k, v in top.items())
    if any(w in q for w in ("licen", "edition", "option", "entitlement")):
        lp = a.licence_position
        lines = [f"### Licence position (indicative - requires SME validation)",
                 f"- Proposed optimisation £{a.licence_opt['proposed']:,.0f}/yr ({a.licence_opt['proposed_pct']}% of spend)"]
        for r in lp[lp.delta != 0].sort_values("delta").itertuples():
            lines.append(f"- {r.product}: entitled {r.entitled}, deployed {r.deployed_requirement} -> {r.status}")
        return "\n".join(lines)
    if any(w in q for w in ("block", "missing", "evidence", "gap")):
        b = recs[recs.readiness == "Blocked"]
        return "### Blocked by evidence gaps\n" + "\n".join(f"- {r.instance_id}: {r.recommended_action} - {r.constraints}" for r in b.itertuples())
    if any(w in q for w in ("budget", "20%", "cut")):
        bs = a.budget
        return (f"### Budget scenario (-{a.scenario.budget_cut_pct or 20:.0f}%)\n- Budget £{bs['reduced_budget']:,.0f} vs baseline £{bs['baseline_budget']:,.0f}\n"
                f"- Funded {bs['funded_count']} items, deferred {bs['deferred_count']}\n- Mandatory risk items funded "
                f"{bs['mandatory_funded']}/{bs['mandatory_total']}\n- Recurring savings retained **{bs['saving_retained_pct']}%**")
    if any(w in q for w in ("saving", "cost", "tco", "value", "opportunit")):
        top = recs.sort_values("net_5yr", ascending=False).head(10)
        return "### Top value opportunities (5-yr net)\n" + "\n".join(
            f"- {r.instance_id}: {r.recommended_action} -> {r.target_platform} | £{r.annual_saving:,.0f}/yr | readiness {r.readiness}"
            for r in top.itertuples())
    if any(w in q for w in ("cloud", "azure")):
        c = recs[recs.recommended_action == "Cloud Migrate"]
        return f"### Azure candidates ({len(c)})\n" + c.target_platform.str.replace(r" \(.*\)$", "", regex=True).value_counts().to_string()
    if any(w in q for w in ("risk", "critical")):
        top = risk.sort_values("risk_score", ascending=False).head(8)
        return "### Highest-risk databases\n" + "\n".join(f"- {r.instance_id} ({r.risk_band} {r.risk_score}): {r.risk_reasons}" for r in top.itertuples())
    return executive_summary(a) + "\n\n_Tip: ask about lifecycle, licences, blocked evidence, savings, budget, Azure, risk or an instance id such as ORA-0001._"
