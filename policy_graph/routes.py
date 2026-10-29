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
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from flask import Response, jsonify, render_template, request

from . import proposals, service
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
    except proposals.ProposalError as exc:
        return _error(str(exc), 400)
    except proposals.ProposalConflict as exc:
        return _error(str(exc), 409)
    except proposals.NotConfigured as exc:
        return _error(str(exc), 503)
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
        raise service.BadRequest("agent is required (DeciderAgent | SummarizerAgent | FeedbackAgent | CompanyExtractionAgent)")
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
        raise service.BadRequest("id must match ^(DA|SA|FA|CA)(\\.[a-z0-9_]+)+$")
    return node_id


def register_policy_graph_routes(app, *, engine, get_config_hash, repo_root, is_margin_account,
                                 llm=None, proposal_context=None, activate=None, proposal_model=None,
                                 learning_runner=None) -> None:
    """`llm(role, system_text, user_text) -> str` (roles: drafter, critic), `proposal_context(config_hash,
    agent_type) -> dict` (diagnostics, evidence, verdict history) and `activate` (prompt_manager
    .set_active_prompt_version) are optional: without them the proposal routes answer 503."""
    repo_root = Path(repo_root)
    is_margin_account = bool(is_margin_account)
    common = dict(repo_root=repo_root, is_margin_account=is_margin_account)
    replay_jobs, replay_lock, replay_pool = {}, threading.Lock(), None

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
            factors = _bool(request.args.get("factors"), True)
            raw_days = request.args.get("factor_days")
            factor_days = int(raw_days) if raw_days and _VERSION_RE.match(str(raw_days)) else 90
            return jsonify(service.graph_payload(engine, config_hash, agent, version, layer=layer, refs=refs,
                                                 factors=factors, factor_days=max(7, min(factor_days, 3650)), **common))
        return _run(go)

    @app.route("/api/policy-graph/node", methods=["GET"])
    def policy_graph_node():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg()
            version = _version_arg()
            node_id = _id_arg()
            raw_days = request.args.get("factor_days")
            factor_days = int(raw_days) if raw_days and _VERSION_RE.match(str(raw_days)) else 90
            return jsonify(service.node_payload(engine, config_hash, agent, version, node_id,
                                                factor_days=max(7, min(factor_days, 3650)), **common))
        return _run(go)

    @app.route("/api/policy-graph/learning", methods=["GET"])
    def policy_graph_learning():
        config_hash = get_config_hash()

        def go():
            from .learning import learning_payload
            raw = request.args.get("days", "90")
            if not _VERSION_RE.fullmatch(str(raw)) or not 1 <= int(raw) <= 3650:
                raise service.BadRequest("days must be an integer between 1 and 3650")
            response = jsonify(learning_payload(engine, config_hash, _agent_arg(default="DeciderAgent"),
                                               _version_arg(), days=int(raw), **common))
            if hasattr(response, "headers"):
                response.headers["Cache-Control"] = "no-store"
            return response
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


    @app.route("/api/policy-graph/paths", methods=["GET"])
    def policy_graph_paths():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg(default="DeciderAgent")
            raw = request.args.get("days")
            days = int(raw) if raw and _VERSION_RE.match(str(raw)) else 90
            return jsonify(service.paths_payload(engine, config_hash, agent, days=days, **common))
        return _run(go)

    @app.route("/api/policy-graph/router", methods=["GET"])
    def policy_graph_router():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg(default="DeciderAgent")
            raw = request.args.get("n")
            last_n = int(raw) if raw and _VERSION_RE.match(str(raw)) else 30
            return jsonify(service.router_payload(engine, config_hash, agent, repo_root=repo_root,
                                                  last_n=max(1, min(last_n, 500))))
        return _run(go)

    # ------------------------------------------------------------------ proposals (Phase 2)
    @app.route("/api/policy-graph/router-cycles", methods=["GET"])
    def policy_router_cycles():
        config_hash = get_config_hash()
        def go():
            from policy_router.shadow_trial import cycle_list
            raw = request.args.get("limit", "100")
            if not _VERSION_RE.fullmatch(str(raw)) or not 1 <= int(raw) <= 200:
                raise service.BadRequest("limit must be an integer between 1 and 200")
            response = jsonify(cycle_list(engine, config_hash, limit=int(raw)))
            if hasattr(response, "headers"):
                response.headers["Cache-Control"] = "no-store"
            return response
        return _run(go)

    @app.route("/api/policy-graph/router-cycles/<int:comparison_id>", methods=["GET"])
    def policy_router_cycle(comparison_id):
        config_hash = get_config_hash()
        def go():
            from policy_router.decisions_log import cycle_detail
            result = cycle_detail(engine, config_hash, comparison_id)
            if result is None:
                raise service.NotFound("Unknown router comparison")
            response = jsonify(result)
            if hasattr(response, "headers"):
                response.headers["Cache-Control"] = "no-store"
            return response
        return _run(go)

    def _json_body() -> dict:
        body = request.get_json(silent=True) if hasattr(request, "get_json") else None
        return body if isinstance(body, dict) else {}

    # Explicit replay controls. GETs and page loads never invoke the runner.
    def _replay_body():
        from .learning_replay import MODES
        origin = request.headers.get("Origin") if hasattr(request, "headers") else None
        if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.scheme, request.host):
            raise service.BadRequest("Replay requests must come from this dashboard")
        if getattr(request, "content_length", 0) and request.content_length > 16384:
            raise service.BadRequest("Replay request is too large")
        body = _json_body()
        ids = body.get("source_input_ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 6 or any(
                isinstance(i, bool) or not isinstance(i, int) or i < 1 for i in ids):
            raise service.BadRequest("Choose between 1 and 6 exact saved input IDs")
        candidate = body.get("candidate_version")
        if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
            raise service.BadRequest("candidate_version must be a non-negative integer")
        mode = body.get("assembly_mode", "captured_subgraph_edits")
        if mode not in MODES:
            raise service.BadRequest("Unknown replay assembly mode")
        spec = body.get("outcome_spec") or {"horizon": 3}
        if not isinstance(spec, dict) or isinstance(spec.get("horizon"), bool) or spec.get("horizon") not in (1, 3, 5):
            raise service.BadRequest("Paper horizon must be 1, 3 or 5 sessions")
        return body, dict(source_input_ids=ids, candidate_version=candidate, assembly_mode=mode,
                          outcome_spec={"horizon": spec["horizon"]}, max_calls=12)

    @app.route("/api/policy-graph/learning/replay-preview", methods=["POST"])
    def policy_learning_replay_preview():
        def go():
            from .learning_replay import preview_comparison
            _body, kwargs = _replay_body()
            return jsonify(preview_comparison(engine, get_config_hash(), **kwargs))
        return _run(go)

    @app.route("/api/policy-graph/learning/replay", methods=["POST"])
    def policy_learning_replay_start():
        def go():
            nonlocal replay_pool
            from .learning_replay import preview_comparison, run_comparison
            body, kwargs = _replay_body()
            if learning_runner is None:
                return _error("Replay model client is not configured", 503)
            config_hash = get_config_hash()
            expected = body.get("expected_cohort_hash")
            if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise service.BadRequest("Preview this exact comparison before running it")
            preview = preview_comparison(engine, config_hash, **kwargs)
            if not preview.get("compatible"):
                return _error("; ".join(preview.get("errors") or ["Comparison is incompatible"]), 400)
            if preview.get("cohort_hash") != expected:
                return _error("Saved comparison changed; preview it again", 409)
            with replay_lock:
                if any(j["status"] in ("queued", "running") for j in replay_jobs.values()):
                    return _error("A policy replay is already running", 409)
                completed = sorted(replay_jobs, key=lambda key: replay_jobs[key]["created"])
                for old in completed[:-11]:
                    replay_jobs.pop(old, None)
                job_id = uuid.uuid4().hex
                replay_jobs[job_id] = {"status": "queued", "created": time.time(), "config_hash": config_hash}
                if replay_pool is None:
                    replay_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="policy-replay")

            def work():
                with replay_lock:
                    replay_jobs[job_id]["status"] = "running"
                try:
                    def scoped_runner(request_data):
                        return learning_runner({**request_data, "config_hash": config_hash})
                    result = run_comparison(engine, config_hash, runner=scoped_runner,
                                            expected_cohort_hash=expected, **kwargs)
                    with replay_lock:
                        replay_jobs[job_id].update(status="complete", result=result)
                except Exception as exc:
                    # Provider errors can echo requests. Never expose their raw message.
                    with replay_lock:
                        replay_jobs[job_id].update(status="error", error=f"Replay stopped ({type(exc).__name__}); no policy activated")
            replay_pool.submit(work)
            return jsonify({"job_id": job_id, "status": "queued"}), 202
        return _run(go)

    @app.route("/api/policy-graph/learning/replay-jobs/<job_id>", methods=["GET"])
    def policy_learning_replay_job(job_id):
        with replay_lock:
            job = replay_jobs.get(job_id)
            if not job or job["config_hash"] != get_config_hash():
                return _error("Replay job unavailable for this configuration", 404)
            result = {k: v for k, v in job.items() if k not in ("created", "config_hash")}
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/policy-graph/proposals", methods=["GET"])
    def policy_graph_proposals_list():
        config_hash = get_config_hash()

        def go():
            agent = _agent_arg()
            raw = request.args.get("limit")
            limit = int(raw) if raw and _VERSION_RE.match(str(raw)) else 20
            return jsonify(proposals.list_proposals(engine, config_hash, agent, limit=max(1, min(limit, 100)), **common))
        return _run(go)

    @app.route("/api/policy-graph/proposals", methods=["POST"])
    def policy_graph_proposals_draft():
        config_hash = get_config_hash()

        def go():
            body = _json_body()
            agent = (body.get("agent_type") or body.get("agent") or "").strip()
            if agent not in AGENT_PREFIX:
                raise service.BadRequest("agent_type is required (DeciderAgent | SummarizerAgent | FeedbackAgent)")
            focus = str(body.get("focus") or "")
            model = proposal_model() if callable(proposal_model) else proposal_model
            return jsonify(proposals.start_draft(engine, config_hash, agent, llm=llm, context_fn=proposal_context,
                                                 focus=focus, created_by="dashboard", model=model, **common))
        return _run(go)

    @app.route("/api/policy-graph/proposals/<int:proposal_id>", methods=["GET"])
    def policy_graph_proposal_get(proposal_id):
        return _run(lambda: jsonify(proposals.get_proposal(engine, proposal_id, **common)))

    @app.route("/api/policy-graph/proposals/<int:proposal_id>/apply", methods=["POST"])
    def policy_graph_proposal_apply(proposal_id):
        def go():
            body = _json_body()
            approved = body.get("approved")
            if not isinstance(approved, list):
                raise service.BadRequest("approved must be a list of guideline ids")
            return jsonify(proposals.apply_proposal(engine, proposal_id, approved, activate=activate,
                                                    actor="dashboard", **common))
        return _run(go)

    @app.route("/api/policy-graph/proposals/<int:proposal_id>/reject", methods=["POST"])
    def policy_graph_proposal_reject(proposal_id):
        def go():
            body = _json_body()
            return jsonify(proposals.reject_proposal(engine, proposal_id, reason=str(body.get("reason") or ""),
                                                     actor="dashboard"))
        return _run(go)


__all__ = ["register_policy_graph_routes", "BUSY_MESSAGE"]
