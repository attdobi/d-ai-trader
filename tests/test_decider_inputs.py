"""decider_inputs — the per-call replay log of the Decider (policy_graph/inputs.py), its migration in
init_database.py, the trader's best-effort writers (exercised from the decider_agent source with stub
globals — the module itself imports config) and the PromptManager's raw-reply record. SQLite only."""
from __future__ import annotations

import ast
import json
import types
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from policy_graph import inputs as I
from policy_graph.assembly import Context

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    I.ensure_schema(engine)
    yield engine
    engine.dispose()


# ----------------------------------------------------------------------------- schema + migration
def test_schema_has_every_column_and_is_idempotent(db):
    I.ensure_schema(db)                       # second run is a no-op
    cols = [c["name"] for c in inspect(db).get_columns("decider_inputs")]
    assert tuple(cols) == I.COLUMNS
    for col in ("system_prompt", "user_prompt", "policy_soul", "policy_directives", "policy_memory", "context_json",
                "ltm_ids", "raw_reply", "model", "reasoning_effort", "prompt_version", "decided_at", "created_at"):
        assert col in I.DDL_POSTGRES
    assert I.DDL_POSTGRES.strip().startswith("CREATE TABLE IF NOT EXISTS decider_inputs")
    assert "SERIAL" not in I.DDL_SQLITE and "AUTOINCREMENT" in I.DDL_SQLITE


def test_init_database_migrates_decider_inputs_from_the_module_ddl():
    tree = ast.parse((ROOT / "init_database.py").read_text(encoding="utf-8"))
    init = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "initialize_database")
    imports = [n for n in ast.walk(init) if isinstance(n, ast.ImportFrom) and n.module == "policy_graph.inputs"]
    assert imports and {a.name for a in imports[0].names} >= {"DDL_POSTGRES", "INDEX_RUN_SQL"}
    ensured = [n for n in ast.walk(init) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ensure_table"
               and len(n.args) >= 3 and isinstance(n.args[2], ast.Constant) and n.args[2].value == "decider_inputs"]
    assert len(ensured) == 1


# ----------------------------------------------------------------------------- payload helpers
def test_context_payload_keeps_actual_lists():
    ctx = Context(regime="MIXED", holdings=["NVDA", "", "AMD"], watchlist=["CMG"], quarantined=["IRDM"],
                  news=["AAPL", None, "AAPL"], entities=["MSFT"], trend=[])
    out = I.context_payload(ctx)
    assert out == {"regime": "MIXED", "holdings": ["NVDA", "AMD"], "watchlist": ["CMG"], "quarantined": ["IRDM"],
                   "news": ["AAPL", "AAPL"], "entities": ["MSFT"], "trend": []}
    assert I.context_payload({"regime": None, "holdings": ("X",)}, trend=["Y"])["trend"] == ["Y"]
    assert I.context_payload(None) == {k: ([] if k != "regime" else "") for k in I.CONTEXT_KEYS}


def test_ltm_row_ids_and_raw_text():
    assert I.ltm_row_ids([{"id": 18}, {"id": "4"}, "DA.ltm.2", 18, {"content": "no id"}, "junk"]) == [18, 4, 2]
    assert I.raw_text('{"decisions": []}') == '{"decisions": []}'
    assert json.loads(I.raw_text({"decisions": [{"ticker": "AAA"}]})) == {"decisions": [{"ticker": "AAA"}]}
    assert I.raw_text(None) is None


# ----------------------------------------------------------------------------- write + replay
def test_record_input_then_reply_roundtrip(db):
    rid = I.record_input(
        db, "h", run_id="20261002T103000", prompt_version=23, system_prompt="SYS", user_prompt="USER",
        policy={"soul": "S", "directives": "D", "memory": "M"},
        context={"regime": "RISK-ON", "holdings": ["NVDA"], "watchlist": ["CMG", "TGT"]},
        ltm_ids=[{"id": 18, "content": "x"}, {"id": 1, "content": "y"}], model="gpt-5.4", reasoning_effort="high",
        decided_at=datetime(2026, 10, 2, 10, 30))
    assert isinstance(rid, int)
    assert I.record_reply(db, rid, "RAW TEXT", model="gpt-4.1", system_prompt="SYS\n\nREASONING DEPTH")
    rows = I.load_inputs(db, "h", "20261002T103000")
    assert len(rows) == 1
    r = rows[0]
    assert r["call_kind"] == I.CALL_DECIDE and r["prompt_version"] == 23
    assert r["system_prompt"] == "SYS\n\nREASONING DEPTH" and r["user_prompt"] == "USER"     # exact bytes sent
    assert (r["policy_soul"], r["policy_directives"], r["policy_memory"]) == ("S", "D", "M")
    assert r["context_json"]["watchlist"] == ["CMG", "TGT"] and r["context_json"]["quarantined"] == []
    assert r["ltm_ids"] == [18, 1]
    assert r["raw_reply"] == "RAW TEXT"
    assert r["model"] == "gpt-4.1" and r["reasoning_effort"] == "high"       # fallback model replaces, effort kept
    # a second call of the same run (the citation repair) is its own row
    rid2 = I.record_input(db, "h", run_id="20261002T103000", prompt_version=23, system_prompt="auditor",
                          user_prompt="cite these", call_kind=I.CALL_CITATION_REPAIR)
    I.record_reply(db, rid2, {"citations": {"AAA": ["DA.x"]}})
    assert [x["call_kind"] for x in I.load_inputs(db, "h", "20261002T103000")] == ["decide", "citation_repair"]
    only = I.load_inputs(db, "h", "20261002T103000", call_kind="citation_repair")
    assert len(only) == 1 and json.loads(only[0]["raw_reply"]) == {"citations": {"AAA": ["DA.x"]}}
    assert only[0]["context_json"] == {} and only[0]["ltm_ids"] == []
    assert I.latest_input(db, "h")["id"] == rid
    assert I.latest_input(db, "other") is None


def test_record_reply_without_row_is_false(db):
    assert I.record_reply(db, None, "x") is False
    assert I.record_reply(db, 9999, "x") is False


# ----------------------------------------------------------------------------- the trader's writers (fail safe)
def _trader_funcs(*names):
    """Compile the named top-level functions of decider_agent.py without importing it (it imports config)."""
    tree = ast.parse((ROOT / "decider_agent.py").read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in nodes} == set(names)
    return compile(ast.Module(body=nodes, type_ignores=[]), "decider_agent.py", "exec")


def _namespace(engine, *, last_reply=None, replies=None):
    calls = []

    class _PM:
        def ask_openai(self, prompt, system_prompt, agent_name=None):
            calls.append((prompt, system_prompt, agent_name))
            return (replies or [{}]).pop(0)

        def last_reply(self):
            return last_reply

    ns = {"engine": engine, "get_agent_model": lambda agent: "gpt-test", "get_current_config_hash": lambda: "h",
          "get_reasoning_params": lambda agent, model: {"reasoning_effort": "high"},
          "prompt_manager": _PM(), "_CASH_HOLD_FALLBACK_CITES": ["DA.code.cash_disclosure"]}
    exec(_trader_funcs("_log_decider_input", "_log_decider_reply", "_repair_missing_citations"), ns)
    return ns, calls


def test_trader_writer_logs_one_row_and_the_raw_reply(db):
    ns, _calls = _namespace(db, last_reply={"model": "gpt-4.1", "reasoning_effort": None, "content": "[{\"action\":\"hold\"}]",
                                            "system_prompt": "SYS!", "user_prompt": "USER"})
    rid = ns["_log_decider_input"]("h", "run1", 23, system_prompt="SYS", user_prompt="USER",
                                   policy={"soul": "S", "directives": "D", "memory": "M"},
                                   context={"regime": "MIXED", "holdings": ["AAA"]}, ltm_ids=[{"id": 7}])
    assert isinstance(rid, int)
    pre = I.load_inputs(db, "h", "run1")[0]
    assert pre["model"] == "gpt-test" and pre["reasoning_effort"] == "high" and pre["raw_reply"] is None
    ns["_log_decider_reply"](rid, [{"action": "hold"}])
    row = I.load_inputs(db, "h", "run1")[0]
    assert row["model"] == "gpt-4.1" and row["raw_reply"] == "[{\"action\":\"hold\"}]" and row["system_prompt"] == "SYS!"
    assert row["reasoning_effort"] is None                   # the fallback model was sent no reasoning effort
    assert row["ltm_ids"] == [7] and row["context_json"]["holdings"] == ["AAA"]
    # a client that reports nothing: the parsed reply the trader received is kept as text
    ns2, _ = _namespace(db, last_reply=None)
    rid2 = ns2["_log_decider_input"]("h", "run2", 23, system_prompt="S", user_prompt="U")
    ns2["_log_decider_reply"](rid2, {"error": "GPT-5 failed: length"})
    row2 = I.load_inputs(db, "h", "run2")[0]
    assert json.loads(row2["raw_reply"]) == {"error": "GPT-5 failed: length"} and row2["model"] == "gpt-test"


def test_trader_writer_never_raises(capsys):
    class _Broken:
        dialect = types.SimpleNamespace(name="sqlite")

        def begin(self):
            raise RuntimeError("db down")

        connect = begin

    ns, _calls = _namespace(_Broken())
    assert ns["_log_decider_input"]("h", "run1", 23, system_prompt="S", user_prompt="U") is None
    ns["_log_decider_reply"](None, {"x": 1})                  # no row → nothing to do
    ns["_log_decider_reply"](5, {"x": 1})                     # write fails → one log line, no exception
    out = capsys.readouterr().out
    assert "decider_inputs row not written (decide): db down" in out
    assert "decider_inputs reply not written: db down" in out


def test_repair_call_is_logged_and_never_carries_considered_items(db):
    ns, calls = _namespace(db, last_reply=None, replies=[{"citations": {"TSLA": ["DA.directives.strategy.harvest"]}}])
    decisions = [{"action": "sell", "ticker": "TSLA", "reason": "harvest"},
                 {"kind": "considered_audit", "considered": [{"ticker": "CMG", "verdict": "reject", "why": "chase"}]}]
    ns["_repair_missing_citations"](decisions, {"DA.directives.strategy.harvest"}, "DA.directives.strategy.harvest — HARVEST",
                                    "run9", prompt_version=23, config_hash="h")
    assert len(calls) == 1 and "TSLA / SELL" in calls[0][0] and "CMG" not in calls[0][0]
    assert decisions[0]["reason"].endswith("[cites: DA.directives.strategy.harvest]")
    rows = I.load_inputs(db, "h", "run9")
    assert [r["call_kind"] for r in rows] == ["citation_repair"]
    assert json.loads(rows[0]["raw_reply"]) == {"citations": {"TSLA": ["DA.directives.strategy.harvest"]}}


def test_no_repair_call_when_only_considered_items_are_uncited(db):
    ns, calls = _namespace(db)
    decisions = [{"action": "hold", "ticker": "AAA", "reason": "keep [cites: DA.x]"}]
    ns["_repair_missing_citations"](decisions, {"DA.x"}, "DA.x — X", "run10", prompt_version=23, config_hash="h")
    assert calls == [] and I.load_inputs(db, "h", "run10") == []


# ----------------------------------------------------------------------------- decider wiring (source contract)
def _ask():
    tree = ast.parse((ROOT / "decider_agent.py").read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "ask_decision_agent")


def _call_lines(fn, name):
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            label = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if label == name:
                out.append(n)
    return out


def test_decider_logs_the_input_before_the_call_and_the_reply_after():
    ask = _ask()
    ask_calls = [c for c in _call_lines(ask, "ask_openai")]
    assert len(ask_calls) == 1
    before = _call_lines(ask, "_log_decider_input")
    after = _call_lines(ask, "_log_decider_reply")
    assert len(before) == 1 and len(after) == 1
    assert before[0].lineno < ask_calls[0].lineno < after[0].lineno
    kw = {k.arg for k in before[0].keywords}
    assert {"system_prompt", "user_prompt", "policy", "context", "ltm_ids"} <= kw


def test_decider_records_rejections_and_tags_memory_rows():
    ask = _ask()
    rc = _call_lines(ask, "_record_cited")
    assert len(rc) == 1 and "considered" in {k.arg for k in rc[0].keywords}
    fl = _call_lines(ask, "format_long_term_memory")
    assert len(fl) == 1 and "cite_tag" in {k.arg for k in fl[0].keywords}
    assert len(_call_lines(ask, "_fold_considered")) == 1
    # the repair pass is handed the decisions only — never the considered array
    rep = _call_lines(ask, "_repair_missing_citations")
    assert len(rep) == 1 and all(getattr(a, "id", "") != "considered_setups" for a in rep[0].args)


# ----------------------------------------------------------------------------- PromptManager raw-reply record
def test_prompt_manager_records_the_raw_reply(monkeypatch):
    from tests.test_config_model_overrides import _import_config
    cfg = _import_config(monkeypatch, env={"DAI_GPT_MODEL": "gpt-5.4", "DAI_MODEL_DECIDER": None,
                                           "DAI_DECIDER_REASONING_LEVEL": "high", "DAI_REASONING_LEVEL": None,
                                           "DAI_DISABLE_REASONING_PARAM": None})
    sent = {}

    class _Completions:
        def create(self, **params):
            sent.update(params)
            msg = types.SimpleNamespace(content='  {"decisions": [], "considered": []}  ')
            return types.SimpleNamespace(choices=[types.SimpleNamespace(finish_reason="stop", message=msg)], usage=None)

    client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=_Completions()))
    pm = cfg.PromptManager(client=client, session=None)
    assert pm.last_reply() is None
    out = pm.ask_openai("USER PROMPT", "SYSTEM PROMPT", agent_name="DeciderAgent")
    assert out == {"decisions": [], "considered": []}
    last = pm.last_reply()
    assert last["model"] == "gpt-5.4" and last["agent"] == "DeciderAgent"
    assert last["content"] == '  {"decisions": [], "considered": []}  '          # raw, before strip/parse
    assert last["user_prompt"] == "USER PROMPT"
    assert last["system_prompt"] == sent["messages"][0]["content"]                 # exactly what went out
    assert last["reasoning_effort"] == sent.get("reasoning_effort")
