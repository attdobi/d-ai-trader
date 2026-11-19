"""Compare text and screenshot routing on one saved cycle. Preview is read-only."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from policy_graph.learning_replay import (
    TAG_RE, ReplayError, _credential_guard, _source_image_bundle, _source_inputs,
)
from policy_router.decisions import DecisionsSettings, build_request, route_shadow_cycle
from policy_router.decisions_log import record_shadow
from policy_router.features import CycleContext, parse_summary_row
from policy_router.nodes import RouterNode
from policy_router.replay import BODY_ID, memory_lines


def prepare(engine, config_hash, input_id, screenshot_root):
    source = _source_inputs(engine, config_hash, [input_id])[0]
    images = _source_image_bundle(source, config_hash, screenshot_root)
    if not images or not images.attachments or images.omissions:
        raise ReplayError("a complete recorded screenshot bundle is required for comparison")

    # Keep source order and collapse multiple screenshots of the same summary.
    provenance = dict.fromkeys(
        (item.summary_id, item.source_run_id, item.source_agent) for item in images.attachments
    )
    summaries = []
    with engine.connect() as conn:
        for summary_id, run_id, agent in provenance:
            if not str(summary_id).isdigit() or not run_id or not agent:
                raise ReplayError("recorded summary provenance is incomplete")
            data = conn.execute(text("""
                SELECT data FROM summaries WHERE id=:id AND config_hash=:config_hash
                  AND run_id=:run_id AND agent=:agent AND timestamp<=:decision_time
            """), {
                "id": int(summary_id), "config_hash": config_hash, "run_id": run_id,
                "agent": agent, "decision_time": source["decided_at"],
            }).scalar_one_or_none()
            summary = parse_summary_row(data)
            if not summary or not (summary["headlines"] or summary["insights"].strip()):
                raise ReplayError("recorded summary has no usable text")
            summaries.append(summary)
        event_block = conn.execute(text("""
            SELECT block FROM event_risk_snapshots
            WHERE config_hash=:config_hash AND run_id=:run_id AND as_of<=:decision_time
            ORDER BY as_of DESC LIMIT 1
        """), {
            "config_hash": config_hash, "run_id": source["run_id"],
            "decision_time": source["decided_at"],
        }).scalar()

    body, _ = memory_lines(source)
    nodes = [
        RouterNode(ident, "ltm", BODY_ID.sub("", line.strip()), len(line))
        for ident, line in body.items()
    ]
    payload = source["context_json"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    context = CycleContext(
        regime=payload.get("regime") or "",
        **{key: payload.get(key) or [] for key in (
            "holdings", "watchlist", "quarantined", "news", "entities", "trend",
        )},
        today=datetime.fromisoformat(str(source["decided_at"])),
        run_id=source["run_id"], summaries=summaries, event_block=event_block or "",
    )
    pins = source["system_prompt"]
    return source, context, nodes, {
        "pinned_policy": pins, "pinned_ids": sorted(set(TAG_RE.findall(pins))), "today_ids": list(body),
    }, images


def run(engine, config_hash, input_id, *, screenshot_root, execute=False, api_key=None):
    source, context, nodes, options, images = prepare(engine, config_hash, input_id, screenshot_root)
    arms = (("text", None), ("images", images))
    # Validate both inputs before the first paid call. Only pixels and their source manifest vary.
    for _, bundle in arms:
        payload, *_ = build_request(
            context, nodes, pinned_policy=options["pinned_policy"],
            pinned_ids=options["pinned_ids"], image_bundle=bundle,
        )
        _credential_guard([json.dumps(payload["input"][0]["content"][0]["data"])])
    report = {
        "input_id": input_id, "policy_version": source["prompt_version"],
        "summaries": len(context.summaries), "images": len(images.attachments),
        "optional_memories": len(nodes), "planned_calls": len(arms), "executed": False,
    }
    if not execute:
        return report

    results, selections = {}, {}
    experiment_id = uuid4().hex[:12]
    for arm, bundle in arms:
        result = route_shadow_cycle(
            DecisionsSettings(timeout_s=30), context, nodes,
            image_bundle=bundle, api_key=api_key, **options,
        )
        comparison_id = record_shadow(
            engine, config_hash, source["prompt_version"], f"image-eval-{input_id}-{experiment_id}-{arm}",
            result, source_kind="replay", source_input_id=input_id, served_ids=options["today_ids"],
            context_summary={
                "source_input_id": input_id, "summary_count": len(context.summaries), "regime": context.regime,
            },
        )
        results[arm] = {
            "comparison_id": comparison_id, "status": result.status, "fee": result.cost_usd,
            "latency_ms": result.latency_ms, "selected": len(result.selection.included) if result.selection else None,
        }
        if result.status != "ok":
            break
        selections[arm] = result.selection.include_ids
    changed = sorted(selections["text"] ^ selections["images"]) if len(selections) == len(arms) else None
    return {**report, "executed": True, "arms": results, "changed_selections": changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--input-id", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parent
        load_dotenv(root / ".env", override=False)
        database_url = os.getenv("DATABASE_URI") or os.getenv("DATABASE_URL")
        if not database_url:
            raise ReplayError("configure the primary database for this saved cycle")
        report = run(
            create_engine(database_url), args.config_hash, args.input_id, screenshot_root=root / "screenshots",
            execute=args.execute, api_key=os.getenv("OPENAI_API_KEY") if args.execute else None,
        )
        print(json.dumps(report, indent=2))
        if args.execute and sum(a["status"] == "ok" for a in report["arms"].values()) != 2:
            return 1
        return 0
    except ReplayError as exc:
        print(str(exc))
    except Exception as exc:
        print(type(exc).__name__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
