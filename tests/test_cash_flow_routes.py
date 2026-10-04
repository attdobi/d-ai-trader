"""/api/cash-flows routes (cash_flow_routes.py) on a real Flask app over in-memory SQLite."""
from __future__ import annotations

import importlib
import sys
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, text

import cash_flows as cf

CFG = "cfg_test"
TODAY = date(2026, 10, 4)


@pytest.fixture
def env():
    flask = pytest.importorskip("flask")
    eng = create_engine("sqlite://")
    cf.ensure_schema(eng)
    with eng.begin() as conn:
        for key, day, amount, cfg in [("131462110360", "2026-09-23", 700.0, CFG),
                                      ("131720324255", "2026-09-25", 22.82, CFG),
                                      ("122773096373", "2026-06-23", -500.0, CFG),
                                      ("other", "2026-09-24", 5000.0, "cfg_other")]:
            conn.execute(text("""
                INSERT INTO external_cash_flows (config_hash, txn_key, flow_date, amount, description)
                VALUES (:c, :k, :d, :a, 'JOURNAL FRM 53822742')
            """), {"c": cfg, "k": key, "d": day, "a": amount})
    calls = []

    def sync(config_hash):
        calls.append(config_hash)
        return {"status": "ok", "fetched": 2, "inserted": 0}

    from cash_flow_routes import register_cash_flow_routes
    app = flask.Flask("cash_flow_test")
    register_cash_flow_routes(app, engine=eng, get_config_hash=lambda: CFG, sync=sync,
                              baseline=lambda h: (1474.63, datetime(2026, 7, 1, 9, 0)), today=lambda: TODAY)
    ids = {f["txn_key"]: f["id"] for f in cf.list_flows(eng, CFG)}
    other_id = cf.list_flows(eng, "cfg_other")[0]["id"]
    return {"client": app.test_client(), "engine": eng, "ids": ids, "other_id": other_id, "sync_calls": calls}


def test_get_lists_scoped_flows_with_totals_and_gain(env):
    r = env["client"].get("/api/cash-flows?current_value=3217.15")
    assert r.status_code == 200
    d = r.get_json()
    assert d["config_hash"] == CFG
    assert [f["date"] for f in d["flows"]] == ["2026-06-23", "2026-09-23", "2026-09-25"]   # no other config
    assert d["flows"][1]["label"] == "+$700 deposit" and d["flows"][1]["source"] == "schwab"
    assert d["flows"][0]["in_gain_period"] is False                                        # before the baseline
    assert d["totals"]["all"]["net"] == 222.82
    assert d["totals"]["since_baseline"]["net"] == 722.82 and d["totals"]["since_baseline"]["since"] == "2026-07-01"
    assert d["baseline"] == {"value": 1474.63, "date": "2026-07-01", "at": "2026-07-01T09:00:00"}
    assert d["gain"]["net_flows"] == 722.82 and d["gain"]["net_gain_loss"] == pytest.approx(3217.15 - 1474.63 - 722.82, abs=0.01)
    assert d["sync_available"] is True
    # The page can pin the baseline it rendered (query wins over the callback).
    d2 = env["client"].get("/api/cash-flows?current_value=3217.15&baseline_value=1000&baseline_at=2026-09-24").get_json()
    assert d2["gain"]["net_flows"] == 22.82 and d2["gain"]["baseline_value"] == 1000
    assert env["client"].get("/api/cash-flows?current_value=abc").status_code == 400


def test_post_manual_transfer_validates_and_dedupes(env):
    c = env["client"]
    r = c.post("/api/cash-flows", json={"date": "2026-09-24", "amount": 700, "direction": "deposit", "note": "from checking"})
    assert r.status_code == 201
    f = r.get_json()["flow"]
    assert f["source"] == "manual" and f["amount"] == 700.0 and f["note"] == "from checking"
    assert f["duplicate_of"] == env["ids"]["131462110360"] and f["counted"] is False
    r = c.post("/api/cash-flows", json={"date": "2026-10-01", "amount": "40.50", "direction": "withdrawal"})
    assert r.status_code == 201 and r.get_json()["flow"]["amount"] == -40.5
    totals = c.get("/api/cash-flows").get_json()["totals"]["since_baseline"]
    assert totals["net"] == 682.32 and totals["duplicates"] == 1

    for body, needle in [
        ({"date": "2026-10-05", "amount": 10, "direction": "deposit"}, "future"),
        ({"date": "2026-10-01", "amount": 0, "direction": "deposit"}, "greater than 0"),
        ({"date": "2026-10-01", "amount": -10, "direction": "deposit"}, "greater than 0"),
        ({"date": "2026-10-01", "amount": 10, "direction": "sideways"}, "direction"),
        ({"date": "2026-10-01", "amount": 10, "direction": "deposit", "note": "n" * 201}, "200"),
        ({"amount": 10, "direction": "deposit"}, "date"),
    ]:
        r = c.post("/api/cash-flows", json=body)
        assert r.status_code == 400 and needle in r.get_json()["error"], (body, r.get_json())


def test_delete_only_manual_rows_of_this_config(env):
    c = env["client"]
    fid = c.post("/api/cash-flows", json={"date": "2026-09-30", "amount": 5, "direction": "deposit"}).get_json()["flow"]["id"]
    r = c.delete(f"/api/cash-flows/{fid}")
    assert r.status_code == 200 and r.get_json()["deleted"] == fid
    assert c.delete(f"/api/cash-flows/{fid}").status_code == 404
    r = c.delete(f"/api/cash-flows/{env['ids']['131462110360']}")
    assert r.status_code == 400 and "exclude" in r.get_json()["error"]
    assert c.delete(f"/api/cash-flows/{env['other_id']}").status_code == 404


def test_exclude_toggle_on_schwab_rows(env):
    c = env["client"]
    sid = env["ids"]["131720324255"]
    r = c.post(f"/api/cash-flows/{sid}/exclude", json={"excluded": True})
    assert r.status_code == 200 and r.get_json()["flow"]["excluded"] is True
    assert c.get("/api/cash-flows").get_json()["totals"]["since_baseline"]["net"] == 700.0
    r = c.post(f"/api/cash-flows/{sid}/exclude", json={"excluded": "false"})
    assert r.status_code == 200 and r.get_json()["flow"]["excluded"] is False
    assert c.post(f"/api/cash-flows/{sid}/exclude", json={}).status_code == 400
    assert c.post(f"/api/cash-flows/{sid}/exclude", json={"excluded": "maybe"}).status_code == 400
    mid = c.post("/api/cash-flows", json={"date": "2026-09-30", "amount": 5, "direction": "deposit"}).get_json()["flow"]["id"]
    assert c.post(f"/api/cash-flows/{mid}/exclude", json={"excluded": True}).status_code == 400
    assert c.post(f"/api/cash-flows/{env['other_id']}/exclude", json={"excluded": True}).status_code == 404
    assert c.post("/api/cash-flows/999999/exclude", json={"excluded": True}).status_code == 404


def test_sync_route_never_raises(env):
    flask = pytest.importorskip("flask")
    from cash_flow_routes import register_cash_flow_routes
    r = env["client"].post("/api/cash-flows/sync")
    assert r.status_code == 200 and r.get_json()["status"] == "ok" and env["sync_calls"] == [CFG]

    def boom(_h):
        raise RuntimeError("schwab down")

    for sync, status in [(None, "unavailable"), (boom, "error"), (lambda h: None, "ok")]:
        app = flask.Flask(f"cf_sync_{status}")
        register_cash_flow_routes(app, engine=env["engine"], get_config_hash=lambda: CFG, sync=sync)
        r = app.test_client().post("/api/cash-flows/sync")
        assert r.status_code == 200 and r.get_json()["status"] == status


def test_routes_survive_a_legacy_table_and_import_without_config(monkeypatch):
    flask = pytest.importorskip("flask")
    monkeypatch.delitem(sys.modules, "config", raising=False)
    routes = importlib.import_module("cash_flow_routes")
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(text("""CREATE TABLE external_cash_flows (id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_hash TEXT NOT NULL, txn_key TEXT UNIQUE NOT NULL, flow_date DATE NOT NULL,
            amount DOUBLE PRECISION NOT NULL, description TEXT, recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""))
        conn.execute(text("INSERT INTO external_cash_flows (config_hash, txn_key, flow_date, amount) VALUES (:c, 'k', '2026-09-23', 700)"),
                     {"c": CFG})
    app = flask.Flask("cf_legacy")
    routes.register_cash_flow_routes(app, engine=eng, get_config_hash=lambda: CFG)
    client = app.test_client()
    d = client.get("/api/cash-flows").get_json()
    assert d["flows"][0]["source"] == "schwab" and d["baseline"] is None and d["sync_available"] is False
    # A manual entry migrates the table on first write.
    assert client.post("/api/cash-flows", json={"date": "2026-09-30", "amount": 1, "direction": "deposit"}).status_code == 201
    assert "config" not in sys.modules
