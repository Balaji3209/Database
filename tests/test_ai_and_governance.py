import pytest

from dboptima import ai_advisor, database


def test_masker_pseudonymises_and_restores(analysis):
    inst = analysis.data["database_instances"]
    row = inst[inst.owner != ""].iloc[0]
    m = ai_advisor.Masker(inst)
    text = f"Host {row.hostname} owned by {row.owner} contact someone@else.example"
    masked = m.mask(text)
    assert row.hostname not in masked and row.owner not in masked and "someone@else.example" not in masked
    assert m.unmask(m.mask(f"Host {row.hostname}")) == f"Host {row.hostname}"


def test_verify_numbers_flags_invented_figures(analysis):
    facts = ai_advisor.instance_facts(analysis, "ORA-0001")
    saving = facts["recommendation"]["annual_saving"]
    v = ai_advisor.verify_numbers(f"Saves £{saving:,.0f} a year, payback 25 months, and also £987,654 extra.", facts)
    assert v.set_index("value_in_answer").loc[987654, "traced_to_fact_pack"] == False  # noqa: E712
    assert v[v.value_in_answer.round(0) == round(saving)].traced_to_fact_pack.all()
    assert 25e6 not in set(v.value_in_answer)  # "months" must not be parsed as millions


@pytest.mark.parametrize("iid", ["ORA-0001", "ORA-0004", "MSS-0001", "MSS-0008"])
def test_rules_based_answers_are_fully_traceable(analysis, iid):
    for stage, prompt in ai_advisor.STAGE_PROMPTS.items():
        v = ai_advisor.advise(analysis, prompt, iid, privacy_strict=True)["verification"]
        assert v.empty or v.traced_to_fact_pack.all(), (stage, v[~v.traced_to_fact_pack])


def test_privacy_mode_never_calls_ai(analysis, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("AI layer must not be called in privacy mode")

    monkeypatch.setattr(ai_advisor, "call_azure_openai", boom)
    res = ai_advisor.advise(analysis, "Explain ORA-0001", "ORA-0001", privacy_strict=True)
    assert "privacy" in res["mode"].lower() and "ORA-0001" in res["answer"] and res["masked_prompt"] == ""


def test_ai_failure_falls_back_to_rules(analysis, monkeypatch):
    monkeypatch.setattr(ai_advisor.config, "azure_openai_configured", lambda: True)
    monkeypatch.setattr(ai_advisor, "call_azure_openai", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("down")))
    res = ai_advisor.advise(analysis, "Which databases are blocked?", None, privacy_strict=False)
    assert "fallback" in res["mode"].lower() and "Blocked" in res["answer"]


def test_decision_requires_named_human(tmp_path):
    db = tmp_path / "t.db"
    with pytest.raises(ValueError):
        database.record_decision("REC-X", "X", "Approved", "Upgrade", "  ", "Architect", "", db_path=db)
    database.record_decision("REC-X", "X", "Approved", "Upgrade", "A. Architect", "Architect", "ok", db_path=db)
    log = database.decision_log(db)
    assert len(log) == 1 and log.iloc[0].decided_by == "A. Architect"
