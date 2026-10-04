"""Flask routes of the Dashboard's Cash transfers card (math and storage in cash_flows.py).

`register_cash_flow_routes(app, *, engine, get_config_hash, sync=None, baseline=None, today=None)` is
the only entry point; dashboard_server.py calls it once. Imports only flask and cash_flows (never
config): the config hash is read once per request via `get_config_hash()`.

    GET    /api/cash-flows                  transfers + totals (+ the flow-adjusted gain when the
                                            caller passes ?current_value=…)
    POST   /api/cash-flows                  add a manual transfer {date, amount, direction, note}
    DELETE /api/cash-flows/<id>             delete a manual transfer
    POST   /api/cash-flows/<id>/exclude     {excluded: bool} on a Schwab transfer
    POST   /api/cash-flows/sync             pull Schwab transfers now (never raises; 200 + status)

`sync(config_hash) -> dict` runs the Schwab pull (dashboard_server wires it behind its live-mode
check); None means the button reports "unavailable". `baseline(config_hash) -> (value, at) | None`
is the baseline the headline Net Gain uses (the totals "since baseline" and the gain block use it).

Error envelope: `{"error": "<message>"}` with 400 (bad input), 404 (unknown transfer for this
config) or 500 (unexpected).
"""
from __future__ import annotations

from datetime import date, datetime

from flask import jsonify, request

import cash_flows


def _error(message: str, status: int):
    resp = jsonify({"error": str(message)})
    try:
        resp.status_code = status
        return resp
    except Exception:            # a stub jsonify (tests) returns a plain dict
        return resp, status


def _ok(payload: dict, status: int = 200):
    resp = jsonify(payload)
    if status == 200:
        return resp
    try:
        resp.status_code = status
        return resp
    except Exception:
        return resp, status


def _run(fn):
    try:
        return fn()
    except cash_flows.NotFound as exc:
        return _error(str(exc), 404)
    except cash_flows.CashFlowError as exc:
        return _error(str(exc), 400)
    except Exception as exc:     # noqa: BLE001 — JSON envelope, never an HTML 500 page
        print(f"⚠️  cash-flow route failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}", 500)


def _body() -> dict:
    data = request.get_json(silent=True) if hasattr(request, "get_json") else getattr(request, "json", None)
    if isinstance(data, dict):
        return data
    form = getattr(request, "form", None)
    return dict(form) if form else {}


def _float_arg(name: str):
    raw = (request.args or {}).get(name)
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise cash_flows.CashFlowError(f"{name} must be a number")
    if value != value or value in (float("inf"), float("-inf")):
        raise cash_flows.CashFlowError(f"{name} must be a finite number")
    return value


def _excluded_flag(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0", "yes", "no"):
        return value.strip().lower() in ("true", "1", "yes")
    raise cash_flows.CashFlowError("excluded must be true or false")


def register_cash_flow_routes(app, *, engine, get_config_hash, sync=None, baseline=None, today=None):
    """Attach the /api/cash-flows routes to `app`. `today()` (default date.today) bounds manual dates."""
    today = today or date.today

    def _baseline(config_hash):
        """(value, at) from ?baseline_value=&baseline_at= (what the page rendered) or the callback."""
        b_value = _float_arg("baseline_value")
        b_at_raw = (request.args or {}).get("baseline_at")
        if b_value is not None:
            b_at = None
            if b_at_raw:
                try:
                    b_at = cash_flows.as_datetime(b_at_raw)
                except (ValueError, cash_flows.CashFlowError):
                    raise cash_flows.CashFlowError("baseline_at must be an ISO date or timestamp")
            return b_value, b_at
        if baseline is None:
            return None
        try:
            return baseline(config_hash)
        except Exception as exc:
            print(f"⚠️  cash-flow baseline lookup failed: {exc}")
            return None

    def _payload(config_hash):
        try:                     # once per process: a fresh database gets the table, an old one the columns
            cash_flows.ensure_schema(engine)
        except Exception as exc:
            print(f"⚠️  external_cash_flows schema check failed ({exc}); reading legacy columns")
        flows = cash_flows.list_flows(engine, config_hash)
        base = _baseline(config_hash)
        b_value, b_at = (base if base else (None, None))
        b_date = cash_flows.as_date(b_at) if b_at is not None else None
        out = {
            "config_hash": config_hash,
            "flows": [cash_flows.serialize_flow(f, baseline_date=b_date) for f in flows],
            "totals": {
                "all": cash_flows.flow_totals(flows),
                "since_baseline": cash_flows.flow_totals(flows, since=b_date),
            },
            "baseline": ({"value": round(float(b_value), 2), "date": b_date.isoformat() if b_date else None,
                          "at": b_at.isoformat() if hasattr(b_at, "isoformat") else None}
                         if b_value is not None else None),
            "gain": None,
            "sync_available": sync is not None,
            "rules": {
                "duplicate_window_days": cash_flows.DUPLICATE_WINDOW_DAYS,
                "duplicate_tolerance": cash_flows.DUPLICATE_TOLERANCE,
                "note_max_chars": cash_flows.NOTE_MAX_CHARS,
            },
        }
        current = _float_arg("current_value")
        if current is not None and b_value is not None:
            out["gain"] = cash_flows.flow_adjusted_gain(
                current, b_value, cash_flows.counted_pairs(flows), baseline_at=b_at, as_of=datetime.now())
        return out

    @app.route("/api/cash-flows", methods=["GET"])
    def api_cash_flows_list():
        return _run(lambda: _ok(_payload(get_config_hash())))

    @app.route("/api/cash-flows", methods=["POST"])
    def api_cash_flows_add():
        def _do():
            body = _body()
            config_hash = get_config_hash()
            flow = cash_flows.add_manual_flow(
                engine, config_hash, body.get("date"), body.get("amount"), body.get("direction"),
                note=body.get("note"), today=today())
            return _ok({"flow": cash_flows.serialize_flow(flow)}, 201)
        return _run(_do)

    @app.route("/api/cash-flows/<int:flow_id>", methods=["DELETE"])
    def api_cash_flows_delete(flow_id):
        def _do():
            flow = cash_flows.delete_manual_flow(engine, get_config_hash(), flow_id)
            return _ok({"deleted": flow["id"], "flow": cash_flows.serialize_flow(flow)})
        return _run(_do)

    @app.route("/api/cash-flows/<int:flow_id>/exclude", methods=["POST"])
    def api_cash_flows_exclude(flow_id):
        def _do():
            body = _body()
            if "excluded" not in body:
                raise cash_flows.CashFlowError("excluded (true/false) is required")
            flow = cash_flows.set_excluded(engine, get_config_hash(), flow_id, _excluded_flag(body["excluded"]))
            return _ok({"flow": cash_flows.serialize_flow(flow)})
        return _run(_do)

    @app.route("/api/cash-flows/sync", methods=["POST"])
    def api_cash_flows_sync():
        config_hash = get_config_hash()
        if sync is None:
            return _ok({"status": "unavailable", "message": "Schwab sync is not configured for this dashboard"})
        try:
            result = sync(config_hash)
        except Exception as exc:  # noqa: BLE001 — the button must never 500
            print(f"⚠️  Schwab cash-flow sync failed: {exc}")
            result = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
        if not isinstance(result, dict):
            result = {"status": "ok"}
        return _ok(result)

    return app
