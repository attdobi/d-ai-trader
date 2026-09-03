"""Flask routes of the policy graph (spec section 10).

`register_policy_graph_routes(app, *, engine, get_config_hash, repo_root, is_margin_account)` is the
only entry point; dashboard_server.py calls it once right after `app = Flask(__name__)`.
Imports only flask and policy_graph.*; the config hash is read once per request via
`get_config_hash()` and passed explicitly into the service layer.

Error envelope: every JSON route answers `{"error": "<message>"}` with 400 (bad parameters),
404 (unknown agent/version/node), 500 (round-trip failure / unexpected) or 503 (`StoreBusy`:
"policy graph is being rebuilt — retry").
"""
from __future__ import annotations

import re
from pathlib import Path

from flask import Response, jsonify, render_template, request

from . import service
from .model import AGENT_PREFIX, FIELDS, ID_RE

BUSY_MESSAGE = "policy graph is being rebuilt — retry"
_VERSION_RE = re.compile(r"^\d+$")


def _store_exceptions():
    from . import store
    return store.StoreBusy, store.RoundTripError


def _error(message: str, status: int):
    resp = jsonify({"error": str(message)})
    try:
        resp.status_code = status
        return resp
    except Exception:            # a stub jsonify (tests) returns a plain dict
        return resp, status


def _run(fn):
    """Call `fn()` and translate service/store exceptions into the JSON error envelope."""
    StoreBusy, RoundTripError = _store_exceptions()
    try:
        return fn()
    except StoreBusy:
        return _error(BUSY_MESSAGE, 503)
    except service.BadRequest as exc:
        return _error(str(exc), 400)
    except service.NotFound as exc:
        return _error(str(exc), 404)
    except RoundTripError as exc:
        return _error(f"compiled prompt does not match the stored version: {exc}", 500)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:     # noqa: BLE001 — surface everything as the envelope, never a 500 HTML page
        return _error(f"{type(exc).__name__}: {exc}", 500)


def _text(body, *, mimetype: str, headers: dict | None = None, status: int = 200):
    resp = Response(body, status=status, mimetype=mimetype)
    for k, v in (headers or {}).items():
        try:
            resp.headers[k] = v
        except Exception:
            pass
    return resp


def _bool(value, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _agent_arg(default=None) -> str:
    agent = (request.args.get("agent") or request.args.get("agent_type") or default or "").strip()
    if not agent:
        raise service.BadRequest("agent is required (DeciderAgent | SummarizerAgent | FeedbackAgent)")
    if agent not in AGENT_PREFIX:
        raise service.BadRequest(f"unknown agent {agent!r}")
    return agent


def _version_arg(name: str = "version", *, required: bool = False):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            raise service.BadRequest(f"{name} is required")
        return None
    if not _VERSION_RE.match(str(raw).strip()):
        raise service.BadRequest(f"{name} must be a non-negative integer")
    return int(raw)


def _id_arg() -> str:
    node_id = (request.args.get("id") or "").strip()
    if not node_id or not ID_RE.match(node_id):
        raise service.BadRequest("id must match ^(DA|SA|FA)(\\.[a-z0-9_]+)+$")
    return node_id


def register_policy_graph_routes(app, *, engine, get_config_hash, repo_root, is_margin_account) -> None:
    repo_root = Path(repo_root)
    is_margin_account = bool(is_margin_account)
    common = dict(repo_root=repo_root, is_margin_account=is_margin_account)

    @app.route("/policy-graph")
    def policy_graph_page():
        return render_template("policy_graph.html")

    @app.route("/api/policy-graph/agents", methods=["GET"])
    def policy_graph_agents():
        config_hash = get_config_hash()
        return _run(lambda: jsonify(service.list_agents(engine, config_hash, repo_root=repo_root)))

    @app.route("/api/policy-graph/versions", methods=["GET"])
    def policy_graph_versions():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg()
            return jsonify(service.list_versions(engine, config_hash, agent, **common))
        return _run(go)

    @app.route("/api/policy-graph/graph", methods=["GET"])
    def policy_graph_graph():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg()
            version = _version_arg()
            layer = (request.args.get("layer") or "effective").strip().lower()
            refs = _bool(request.args.get("refs"))
            return jsonify(service.graph_payload(engine, config_hash, agent, version, layer=layer, refs=refs, **common))
        return _run(go)

    @app.route("/api/policy-graph/node", methods=["GET"])
    def policy_graph_node():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg()
            version = _version_arg()
            node_id = _id_arg()
            return jsonify(service.node_payload(engine, config_hash, agent, version, node_id, **common))
        return _run(go)

    @app.route("/api/policy-graph/diff", methods=["GET"])
    def policy_graph_diff():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg()
            a = _version_arg("from", required=True)
            b = _version_arg("to", required=True)
            return jsonify(service.diff_payload(engine, config_hash, agent, a, b, **common))
        return _run(go)

    @app.route("/api/policy-graph/compiled", methods=["GET"])
    def policy_graph_compiled():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg()
            version = _version_arg()
            mode = (request.args.get("mode") or "stored").strip().lower()
            field = (request.args.get("field") or "all").strip()
            if field != "all" and field not in FIELDS:
                raise service.BadRequest(f"field must be 'all' or one of {', '.join(FIELDS)}")
            body, roundtrip = service.compiled_text(engine, config_hash, agent, version, mode=mode, field=field, **common)
            return _text(body, mimetype="text/plain; charset=utf-8",
                         headers={"X-Policy-Roundtrip": roundtrip, "Cache-Control": "no-store"})
        return _run(go)

    @app.route("/api/policy-graph/bundle", methods=["GET"])
    def policy_graph_bundle():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg()
            version = _version_arg()
            body = service.bundle_text(
                engine, config_hash, agent, version,
                include_code=_bool(request.args.get("include_code"), True),
                include_ltm=_bool(request.args.get("include_ltm"), True), **common)
            return _text(body, mimetype="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})
        return _run(go)

    @app.route("/api/policy-graph/file", methods=["GET"])
    def policy_graph_file():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg()
            version = _version_arg(required=True)
            node_id = _id_arg()
            data = service.node_file(engine, config_hash, agent, version, node_id, **common)
            return _text(data, mimetype="text/markdown; charset=utf-8",
                         headers={"Content-Disposition": f'inline; filename="{node_id}.md"', "Cache-Control": "no-store"})
        return _run(go)

    @app.route("/api/policy-graph/rebuild", methods=["POST"])
    def policy_graph_rebuild():
        config_hash = get_config_hash()

        def go():
            body = request.get_json(silent=True) if hasattr(request, "get_json") else None
            body = body or {}
            agent = body.get("agent_type") or body.get("agent") or "all"
            if agent != "all" and agent not in AGENT_PREFIX:
                raise service.BadRequest(f"unknown agent_type {agent!r}")
            version = body.get("version", "all")
            if version not in ("all", None) and not _VERSION_RE.match(str(version)):
                raise service.BadRequest("version must be an integer or 'all'")
            force = _bool(body.get("force"))
            return jsonify(service.rebuild(engine, config_hash, agent, version, force=force,
                                           materialized_by="dashboard", **common))
        return _run(go)


__all__ = ["register_policy_graph_routes", "BUSY_MESSAGE"]
