"""Bounded visual-framing observations for review; never a trading control.

Normalization checks schema/provenance, not whether a model's interpretation is
true. Source identity and image hashes come only from the locally saved manifest.
The optional reader is scoped to saved Decider inputs and exact prospective
input/ticker paper outcomes. It cannot activate policy or infer an executed fill.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from sqlalchemy import bindparam, text

SCHEMA_VERSION = 1
MAX_INPUTS = 12
MAX_OBSERVATIONS = 24
MAX_PER_IMAGE = 2
MAX_CUES = 4
_IMAGE_ID = re.compile(r"^I\d{2}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_TICKER = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_CREDENTIAL = re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|\bAuthorization\s*:\s*Bearer\s+\S+", re.I)
_IMAGE_PAYLOAD = re.compile(r"\b(?:data|image)\s*:|\b(?:base64|image_url|input_image)\b", re.I)
_PROVENANCE = ("source_agent", "summary_id", "source_run_id", "sha256")
_NOTE = (
    "Model-reported visible cues and editorial-framing hypotheses, not verified emotions, "
    "intentions, causal effects, trade instructions or calibrated profit probabilities. "
    "Missing images, associations and outcomes remain unknown."
)


def _decode(value, max_chars=200_000):
    if isinstance(value, str):
        if len(value) > max_chars:
            return None
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


def _short(value, limit):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and not _CREDENTIAL.search(value) and not _IMAGE_PAYLOAD.search(value))


def _enum(value, allowed):
    return isinstance(value, str) and value in allowed


def _manifest_images(manifest):
    manifest = _decode(manifest)
    if not isinstance(manifest, dict) or isinstance(manifest.get("schema_version"), bool) or manifest.get("schema_version") != 1:
        return None
    images = manifest.get("images")
    if (not isinstance(images, list) or len(images) > 12 or isinstance(manifest.get("image_count"), bool)
            or manifest.get("image_count") != len(images)):
        return None
    out = {}
    for row in images:
        if not isinstance(row, dict):
            return None
        image_id = row.get("image_id")
        if (not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id) or not 1 <= int(image_id[1:]) <= 12 or image_id in out
                or not isinstance(row.get("sha256"), str) or not _SHA.fullmatch(row["sha256"])
                or not _short(row.get("source_agent"), 100) or not _short(row.get("source_run_id"), 100)
                or row.get("summary_id") is not None and (isinstance(row["summary_id"], bool)
                    or not isinstance(row["summary_id"], (str, int))
                    or isinstance(row["summary_id"], str) and not _short(row["summary_id"], 100))):
            return None
        out[image_id] = row
    return out


def normalize_observations(reply, local_manifest):
    """Return sanitized observations/rejections without mutating either input.

    Empty/omitted observations are valid. Any claimed provenance must agree with
    the manifest, and source fields/hypothesis IDs cannot be supplied by a model.
    Unknown extra model fields are ignored; image paths and pixels never leave.
    """
    result = {"schema_version": SCHEMA_VERSION, "observations": [], "rejected": [], "note": _NOTE}
    decoded = _decode(reply)
    if not isinstance(decoded, dict):
        result["rejected"].append({"index": None, "reason": "invalid_reply"})
        return result
    values = decoded.get("visual_context")
    if values is None or values == []:
        return result
    if not isinstance(values, list):
        result["rejected"].append({"index": None, "reason": "visual_context_must_be_array"})
        return result
    images = _manifest_images(local_manifest)
    if images is None:
        result["rejected"].append({"index": None, "reason": "missing_or_ambiguous_image_manifest"})
        return result
    seen, per_image = set(), {}
    for index, observation in enumerate(values[:MAX_OBSERVATIONS]):
        why = None
        if not isinstance(observation, dict):
            why = "observation_must_be_object"
        elif not isinstance(observation.get("image_id"), str) or observation["image_id"] not in images:
            why = "unknown_image_id"
        else:
            row = images[observation["image_id"]]
            if "hypothesis_id" in observation:
                why = "reserved_hypothesis_id"
            elif any(key in observation and str(observation[key]) != str(row.get(key)) for key in _PROVENANCE):
                why = "provenance_mismatch"
            elif not _enum(observation.get("editorial_framing"), {"positive", "negative", "mixed", "unclear"}):
                why = "invalid_editorial_framing"
            elif not _enum(observation.get("confidence"), {"low", "medium", "high"}):
                why = "invalid_confidence"
            elif not _enum(observation.get("photo_status"), {"labeled_stock", "labeled_archive", "unknown"}):
                why = "invalid_photo_status"
            elif not _short(observation.get("caveat"), 500):
                why = "missing_or_invalid_caveat"
            else:
                cues = observation.get("observed_cues")
                if not isinstance(cues, list) or not 1 <= len(cues) <= MAX_CUES or not all(_short(cue, 240) for cue in cues):
                    why = "invalid_observed_cues"
                ticker = observation.get("ticker")
                if ticker is not None:
                    ticker = ticker.strip().upper() if isinstance(ticker, str) else None
                    if not ticker or not _TICKER.fullmatch(ticker) or ticker in {"CASH", "UNKNOWN", "NONE", "PORTFOLIO"}:
                        why = "invalid_ticker"
            if not why and per_image.get(row["image_id"], 0) >= MAX_PER_IMAGE:
                why = "per_image_observation_limit"
        if why:
            result["rejected"].append({"index": index, "reason": why})
            continue
        clean = {
            "image_id": row["image_id"], "ticker": ticker,
            "observed_cues": [cue.strip() for cue in cues],
            "editorial_framing": observation["editorial_framing"],
            "confidence": observation["confidence"], "photo_status": observation["photo_status"],
            "caveat": observation["caveat"].strip(),
            "source_agent": row["source_agent"], "summary_id": row.get("summary_id"),
            "source_run_id": row["source_run_id"], "sha256": row["sha256"],
            "record_kind": "model_observation_not_verified",
            "ticker_association": "model_reported_caption_or_headline" if ticker else "unavailable",
        }
        fingerprint = hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if fingerprint in seen:
            result["rejected"].append({"index": index, "reason": "duplicate_observation"})
            continue
        seen.add(fingerprint)
        per_image[row["image_id"]] = per_image.get(row["image_id"], 0) + 1
        clean["hypothesis_id"] = "visual-v1:" + fingerprint[:24]
        result["observations"].append(clean)
    if len(values) > MAX_OBSERVATIONS:
        result["rejected"].append({"index": MAX_OBSERVATIONS, "reason": "observation_limit", "count": len(values) - MAX_OBSERVATIONS})
    return result


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value) if value is not None else None


def _paper_outcomes(conn, config_hash, pairs):
    """Exact prospective linkage only; no temporal/nearest-fill approximation."""
    if not pairs:
        return {}
    ids = sorted({source for source, _ticker in pairs})
    query = text("""SELECT p.input_id,p.ticker,o.horizon,o.status,o.outcome_json
        FROM learning_opportunities p JOIN learning_opportunity_outcomes o ON o.opportunity_id=p.id
        WHERE p.config_hash=:h AND p.input_id IN :ids ORDER BY p.id,o.horizon""").bindparams(bindparam("ids", expanding=True))
    try:
        rows = conn.execute(query, {"h": config_hash, "ids": ids}).mappings().all()
    except Exception:
        return {}
    out = {}
    allowed = {"entry_date", "exit_date", "entry_source", "exit_source", "label", "net_return_pct", "gross_return_pct", "side_cost_bps", "spec_id"}
    for row in rows:
        pair = (row["input_id"], str(row["ticker"] or "").upper())
        if pair not in pairs or row["horizon"] not in (1, 3, 5):
            continue
        value = _decode(row["outcome_json"])
        if not isinstance(value, dict):
            continue
        item = {"horizon": row["horizon"], "status": row["status"], "paper_only": True,
                "association": "exact_input_and_model_reported_ticker; not causal attribution"}
        for key in allowed:
            found = value.get(key)
            if isinstance(found, bool):
                continue
            if key == "label":
                if found in ("winner", "loser", "break_even"):
                    item[key] = found
                continue
            if key in {"net_return_pct", "gross_return_pct", "side_cost_bps"}:
                if isinstance(found, (int, float)) and math.isfinite(found):
                    item[key] = found
                continue
            if isinstance(found, (int, float)) and math.isfinite(found):
                item[key] = found
            elif (isinstance(found, str) and len(found) <= 150
                  and not _CREDENTIAL.search(found) and not _IMAGE_PAYLOAD.search(found)):
                item[key] = found
        out.setdefault(pair, []).append(item)
    return out


def recent_visual_context(engine, config_hash, limit=MAX_INPUTS):
    """Read at most twelve saved Decider inputs and return at most 24 observations.

    No DDL, model call, file access, broker lookup or policy write occurs here.
    Driver diagnostics are intentionally withheld because they can contain local
    connection details. The report is bounded research context, not a scorecard.
    """
    limit = max(1, min(MAX_INPUTS, int(limit)))
    out = {"schema_version": SCHEMA_VERSION, "scope": f"latest {limit} saved decide inputs for one configuration",
           "input_limit": limit, "observation_limit": MAX_OBSERVATIONS, "source_inputs": 0,
           "eligible_observations": 0, "displayed_observations": 0, "rejected_observations": 0,
           "observations": [], "truncated": False, "available": True, "note": _NOTE}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""SELECT id,run_id,prompt_version,decided_at,context_json,raw_reply
                FROM decider_inputs WHERE config_hash=:h AND call_kind='decide'
                ORDER BY id DESC LIMIT :n"""), {"h": config_hash, "n": limit}).mappings().all()
            out["source_inputs"] = len(rows)
            observations = []
            for row in rows:
                context = _decode(row["context_json"])
                manifest = context.get("image_manifest") if isinstance(context, dict) else None
                # A manifest must identify this exact decision; an unbound run
                # cannot establish decision-time visual evidence for another run.
                if isinstance(manifest, dict) and (manifest.get("config_hash") != config_hash
                        or manifest.get("decision_run_id") != row["run_id"]):
                    continue
                normalized = normalize_observations(row["raw_reply"], manifest)
                out["rejected_observations"] += len(normalized["rejected"])
                for observation in normalized["observations"]:
                    observations.append({**observation, "input_id": row["id"], "run_id": row["run_id"],
                                         "prompt_version": row["prompt_version"], "observed_at": _iso(row["decided_at"])})
            out["eligible_observations"] = len(observations)
            observations = observations[:MAX_OBSERVATIONS]
            pairs = {(observation["input_id"], observation["ticker"]) for observation in observations if observation["ticker"]}
            outcomes = _paper_outcomes(conn, config_hash, pairs)
            for observation in observations:
                paper = outcomes.get((observation["input_id"], observation["ticker"]), [])
                observation["paper_outcomes"] = paper
                observation["outcome_status"] = "associated_paper_outcomes" if paper else "unavailable"
            out["observations"] = observations
            out["displayed_observations"] = len(observations)
            out["truncated"] = out["eligible_observations"] > len(observations)
    except Exception:
        out["available"] = False
        out["note"] = "Saved visual observations are unavailable; no evidence or outcomes were inferred."
    return out


__all__ = ["SCHEMA_VERSION", "MAX_INPUTS", "MAX_OBSERVATIONS", "normalize_observations", "recent_visual_context"]
