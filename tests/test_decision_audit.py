import json

from sqlalchemy import create_engine, text

from policy_graph import decision_audit, inputs, opportunities
from policy_graph.citations import DDL_HITS_SQLITE
from policy_router.decisions_log import DDL_SQLITE as ROUTER_DDL


def test_audit_preserves_model_validation_and_execution_boundaries():
    engine = create_engine("sqlite://")
    opportunities.ensure_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE trade_decisions (id INTEGER PRIMARY KEY, config_hash TEXT, "
                          "run_id TEXT, timestamp TEXT, data TEXT)"))
        conn.execute(text(inputs.DDL_SQLITE))
        conn.execute(text(DDL_HITS_SQLITE))
        conn.execute(text(ROUTER_DDL))
        saved = [
            {"ticker": "AAA", "action": "buy", "execution_status": "filled", "reason": "Reclaim [cites: DA.entry]",
             "executed_amount": 123.45, "order_id": "private"},
            {"ticker": "BBB", "action": "buy", "execution_status": "rejected"},
            {"kind": "considered_audit", "considered": [{"ticker": "CCC", "verdict": "watch", "why": "Wait",
                                                       "cited": ["DA.stop"]}]},
        ]
        conn.execute(text("INSERT INTO trade_decisions VALUES (1, 'cfg', 'run', '2026-11-11 07:40:00', :saved), "
                          "(2, 'other', 'run', '2026-11-11 07:40:00', '[]'), "
                          "(3, 'cfg', 'older-unlogged', '2026-11-11 07:42:00', '[]')"), {"saved": json.dumps(saved)})
        reply = json.dumps({"decisions": [{"ticker": ticker, "action": "buy"} for ticker in ("AAA", "BBB", "DDD")]})
        conn.execute(text("""
            INSERT INTO decider_inputs (config_hash, run_id, prompt_version, call_kind, user_prompt, context_json, raw_reply)
            VALUES ('cfg', 'run', 62, 'decide', '# SESSION RECOVERY secret', :context, :reply),
                   ('cfg', 'run', 90, 'citation_repair', 'private', '{}', '[]'),
                   ('other', 'run', 99, 'decide', 'private', '{}', '[]')
        """), {"reply": reply, "context": json.dumps({"regime": "RISK-OFF", "holdings": ["CCC"]})})
        conn.execute(text("""
            INSERT INTO policy_graph_hits (config_hash, agent_type, run_id, node_id, served)
            VALUES ('cfg', 'DeciderAgent', 'run', 'DA.entry', TRUE), ('other', 'DeciderAgent', 'run', 'DA.stop', TRUE)
        """))
        conn.execute(text("""
            INSERT INTO policy_router_comparisons
                (config_hash, run_id, source_input_id, source_kind, status, provider, model, nodes_json, comparison_json, pinned_json)
            VALUES ('cfg', 'run', 1, 'live', 'ok', 'openai', 'router', '[]', '{}', '[]'),
                   ('cfg', 'run', 1, 'replay', 'fallback', 'openai', 'router', '[]', '{}', '[]')
        """))
    opportunities.record_snapshot(engine, "cfg", "run", [{"ticker": "CCC", "price": 100, "sma20": 102}])

    unknown, cycle = decision_audit.audit_cycles(engine, "cfg")["cycles"]
    assert unknown["model_buys"] is None and unknown["filled_buys"] == 0
    assert cycle["version"] == 62 and cycle["at"].endswith("-08:00")
    assert cycle["session_recovery_supplied"]
    assert (cycle["model_buys"], cycle["stored_buys"], cycle["filled_buys"]) == (3, 2, 1)
    assert cycle["decisions"][1]["execution"] == "not filled"
    assert cycle["missing_decisions"][0]["ticker"] == "DDD"
    assert cycle["considered"][0]["passed"] and cycle["served_citations"] == ["DA.entry"]
    assert cycle["router"] == {"id": 1, "status": "ok"}
    assert cycle["screened"] == [{"ticker": "CCC", "ma_distance_pct": -2.0, "held": True}]
    assert "private" not in json.dumps(cycle) and "secret" not in json.dumps(cycle)
    evidence = decision_audit.entry_evidence(engine, "cfg")
    assert evidence["top_first_citations_on_pass_or_watch"] == {"DA.stop": 1}


def test_captured_cash_reply_is_distinct_from_missing_reply():
    row = {"id": 1, "run_id": "run", "timestamp": None, "data": []}
    result = decision_audit._cycle(row, {"raw_reply": '{"decisions": [], "cash_reason": "No qualified entries."}'}, {}, [], set())
    assert result["model_buys"] == 0 and result["cash_reason"] == "No qualified entries."
    assert decision_audit._cycle(row, {"raw_reply": '[null]'}, {}, [], set())["model_buys"] is None
