"""Read-only policy comparisons from candidates and the summaries actually available at decision time."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
import json
from zoneinfo import ZoneInfo

from sqlalchemy import text

from policy_graph import opportunities as opp

PACIFIC = ZoneInfo("America/Los_Angeles")
MAX_SUMMARIES = 10000
MISSING_VERSION = "Unattributed"
ERROR_HEADLINES = {"api error occurred", "max retries reached", "unable to parse ai response", "api error, no response"}
CARD_ACTIONS = {"actionable_now": "BUY", "watch_only": "PASS", "avoid_chasing": "PASS",
                "avoid_failed_catalyst": "PASS"}


def _obj(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _week(instant):
    day = instant.astimezone(PACIFIC).date()
    return (day - timedelta(days=day.weekday())).isoformat()


def _version(version):
    return f"v{version}" if type(version) is int and version >= 0 else MISSING_VERSION


def _summaries(rows, start, end):
    """Keep historic unversioned rows useful for weekly trends, without imputing policy identity."""
    by_id = {}
    for row in rows:
        data = _obj(row["data"])
        try:
            captured = datetime.strptime(data.get("timestamp", ""), "%Y%m%dT%H%M%S").replace(tzinfo=PACIFIC)
        except (TypeError, ValueError):
            captured = datetime.fromisoformat(str(row["timestamp"]))
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=PACIFIC)
        if not start <= captured <= end:
            continue
        prov = _obj(data.get("prompt_provenance"))
        source = prov.get("source")
        version = _version(prov.get("version")) if source in {"global", "config"} else MISSING_VERSION
        if source == "global" and version != MISSING_VERSION:
            version = "Global " + version
        if source == "fallback":
            version = "Fallback prompt"
        body = _obj(data.get("summary"))
        headlines = body.get("headlines")
        insights = body.get("insights")
        headline_ok = isinstance(headlines, list) and any(isinstance(h, str) and h.strip() for h in headlines)
        complete = bool(headline_ok and isinstance(insights, str) and insights.strip()
                        and not body.get("error") and not insights.lower().startswith(("api error", "error parsing"))
                        and not any(str(h).strip().lower() in ERROR_HEADLINES for h in headlines))
        cards = defaultdict(set)
        evidence_cards = body.get("catalyst_validity")
        for card in evidence_cards if isinstance(evidence_cards, list) else []:
            if not isinstance(card, dict):
                continue
            ticker, action = opp._ticker(card.get("ticker")), CARD_ACTIONS.get(str(card.get("tradability")))
            if ticker and action and complete:
                cards[ticker].add(action)
        by_id[str(row["id"])] = dict(captured=captured, version=version, week=_week(captured),
                                     source=row["agent"], run=row["run_id"], complete=complete, cards=cards)
    return by_id


def _summarizer_signal(case, summaries, manifests):
    """One verdict per episode across sources; ignore unmatched, mixed-version or conflicting cards."""
    evidence = manifests.get(case.get("input_id"), [])
    verdicts, versions = set(), set()
    if not isinstance(evidence, list):
        return None
    for image in evidence:
        if not isinstance(image, dict):
            continue
        s = summaries.get(str(image.get("summary_id")))
        if (s is None or s["source"] != image.get("source_agent") or s["run"] != image.get("source_run_id")
                or s["captured"] > opp._now(case["observed_at"])):
            continue
        choices = s["cards"].get(case["ticker"])
        if choices:
            versions.add(s["version"])
            verdicts.update(choices)
    if len(verdicts) != 1 or len(versions) != 1:
        return None
    return dict(case, action=next(iter(verdicts)), summary_version=next(iter(versions)))


def _availability(case, horizon, now):
    outcome = case["outcomes"].get(str(horizon), {})
    if (outcome.get("status") == "matured" and outcome.get("label") in {"winner", "loser", "break_even"}
            and opp._number(outcome.get("net_return_pct")) is not None):
        return "matured"
    if outcome.get("status") not in (None, "pending"):
        return "missing"
    dates = opp._dates(case, horizon)
    if not dates:
        return "missing"
    due = datetime.combine(dates[-1], time(17), tzinfo=opp.ET)
    return "overdue" if now >= due else "pending"


def _scored(group, horizon, now):
    scores = opp.episode_metrics(group, horizon=horizon)
    assessed = [c for c in group if c["action"] in {"BUY", "PASS"}]
    availability = Counter(_availability(c, horizon, now) for c in assessed)
    keys = ("episodes", "assessed", "unassessed", "matured", "tp", "fp", "fn", "tn", "precision",
            "precision_interval", "recall", "recall_interval", "fpr", "fpr_interval", "net_expectancy_pct", "matured_buys")
    return {**{k: scores[k] for k in keys}, "buys": sum(c["action"] == "BUY" for c in assessed),
            "passes": sum(c["action"] == "PASS" for c in assessed),
            **{k: availability[k] for k in ("pending", "overdue", "missing")}}


def _groups(records, summaries, by_week, horizon, now):
    groups, extracts = defaultdict(list), defaultdict(list)
    for row in summaries:
        extracts[row["week"] if by_week else row["version"]].append(row)
    for c in records:
        key = _week(opp._now(c["observed_at"])) if by_week else c.get("summary_version", _version(c["prompt_version"]))
        groups[key].append(c)
    result = []
    for key in groups.keys() | extracts.keys():
        items, docs = groups[key], extracts[key]
        dates = [opp._now(c["observed_at"]) for c in items] + [s["captured"] for s in docs]
        result.append(dict(label=key, first=min(dates).astimezone(PACIFIC).date().isoformat(),
                           last=max(dates).astimezone(PACIFIC).date().isoformat(),
                           summaries=len(docs), complete=sum(s["complete"] for s in docs),
                           with_cards=sum(bool(s["cards"]) for s in docs), **_scored(items, horizon, now)))
    return sorted(result, key=lambda r: (r["last"], r["first"], r["label"]), reverse=True)


def learning_report(engine, config_hash, *, days=30, horizon=3, now=None):
    if days not in (30, 90) or horizon not in opp.HORIZONS:
        raise ValueError("Unsupported reporting window or horizon")
    now = opp._now(now)
    start = now - timedelta(days=days)
    # UTC ISO observation timestamps and market-local summary capture timestamps have different storage contracts.
    params = dict(h=config_hash, start=start.isoformat(), end=now.isoformat(), horizon=horizon,
                  spec=opp.SPEC_ID, side=opp.SIDE_COST_BPS, cap=opp.MAX_REPORT_COHORT + 1,
                  local_start=start.astimezone(PACIFIC).replace(tzinfo=None) - timedelta(days=1),
                  local_end=now.astimezone(PACIFIC).replace(tzinfo=None) + timedelta(days=1))
    scope = """p.config_hash=:h AND p.coverage='prospective_screener' AND p.eligible_for_recall=TRUE
               AND p.spec_id=:spec AND p.side_cost_bps=:side AND p.observed_at BETWEEN :start AND :end"""
    with engine.connect() as conn:
        candidates = conn.execute(text(f"""SELECT p.id,p.ticker,p.observed_at,p.action,p.prompt_version,p.input_id,
                 p.coverage,p.eligible_for_recall,o.outcome_json FROM learning_opportunities p
                 LEFT JOIN learning_opportunity_outcomes o ON p.id=o.opportunity_id AND o.horizon=:horizon AND o.measured_at<=:end
                 WHERE {scope} ORDER BY p.observed_at,p.id LIMIT :cap"""), params).mappings().all()
        if len(candidates) > opp.MAX_REPORT_COHORT:
            return {"status": "cohort_limit", "message": "This window exceeds 50,000 eligible observations. Select 30 days."}
        inputs = conn.execute(text(f"""SELECT d.id,d.context_json FROM decider_inputs d WHERE d.config_hash=:h
                 AND d.call_kind='decide' AND d.id IN (SELECT DISTINCT p.input_id FROM learning_opportunities p
                 WHERE {scope})"""), params).mappings().all()
        summary_rows = conn.execute(text("""SELECT id,agent,timestamp,run_id,data FROM summaries WHERE config_hash=:h
                 AND timestamp BETWEEN :local_start AND :local_end ORDER BY timestamp,id LIMIT :limit"""),
                                    {**params, "limit": MAX_SUMMARIES + 1}).mappings().all()
    cases = [dict(c, outcomes={str(horizon): _obj(c["outcome_json"])}) for c in candidates]
    _, episodes = opp.prospective_episodes(cases, horizon=horizon)
    payload = dict(status="ok", start=start.isoformat(), as_of=now.isoformat(), horizon=horizon, days=days,
                   candidate_rows=len(cases), episodes=len(episodes),
                   decider={group: _groups(episodes, [], group == "week", horizon, now) for group in ("version", "week")})
    if len(summary_rows) > MAX_SUMMARIES:
        payload["summarizer"] = {"status": "cohort_limit"}
        return payload
    summaries = _summaries(summary_rows, start, now)
    manifests = {i["id"]: _obj(_obj(i["context_json"]).get("image_manifest")).get("images") or [] for i in inputs}
    signals = [signal for c in episodes if (signal := _summarizer_signal(c, summaries, manifests))]
    payload["summarizer"] = dict(status="ok", summaries=len(summaries), signals=len(signals),
                                 unattributed=sum(s["version"] == MISSING_VERSION for s in summaries.values()),
                                 **{g: _groups(signals, summaries.values(), g == "week", horizon, now)
                                    for g in ("version", "week")})
    return payload


def review_evidence(engine, config_hash):
    """Compact allowlisted counterpart of the Feedback view, safe to archive with the review."""
    try:
        report = learning_report(engine, config_hash, days=30, horizon=3)
    except Exception:
        return {"status": "unavailable", "scope": "30 days, 3 sessions", "reason": "saved evidence unavailable"}
    if report["status"] != "ok":
        return {"status": report["status"], "scope": "30 days, 3 sessions"}
    packet = {"status": "ok", "start": report["start"], "as_of": report["as_of"], "horizon_sessions": 3,
              "eligible_observations": report["candidate_rows"], "distinct_episodes": report["episodes"]}
    for agent in ("decider", "summarizer"):
        cohort = report[agent]
        if cohort.get("status") == "cohort_limit":
            packet[agent] = {"status": "cohort_limit"}
            continue
        versions = cohort["version"]
        group = {"recorded_groups": len(versions), "latest_groups": []}
        if agent == "summarizer":
            group.update(summaries=cohort["summaries"], unversioned_summaries=cohort["unattributed"],
                         matched_signals=cohort["signals"])
        for row in versions[:3]:
            summary = {key:row[key] for key in ("label","first","last","episodes","assessed","matured",
                        "pending","overdue","missing","buys","passes","matured_buys")}
            for name, hits, total in (("gain_recall", row["tp"],row["tp"]+row["fn"]),
                                      ("loss_fpr", row["fp"],row["fp"]+row["tn"])):
                interval = row["recall_interval" if name == "gain_recall" else "fpr_interval"]
                summary[name] = {"hits":hits, "denominator":total,
                                 "wilson95_pct":[round(x*100,1) for x in interval] if interval else None}
            mean = row["net_expectancy_pct"]
            summary["mean_selected_paper_return_pct"] = round(mean,3) if mean is not None else None
            group["latest_groups"].append(summary)
        packet[agent] = group
    return packet


def review_evidence_text(packet):
    return ("Prospective paper outcomes for non-overlapping eligible screener episodes, with 10 basis points "
            "of costs each way. Gain recall counts selected later winners among all assessed mature winners. "
            "Loss FPR counts selected later losers among assessed mature losers. Summarizer selection uses "
            "actionable versus watch/avoid cards linked by source ID, ticker and decision-time evidence. "
            "Unattributed summaries lack recorded prompt versions. Compare periods with attention to coverage, "
            "pending outcomes, sampling uncertainty and different market conditions. A zero denominator is "
            "unmeasured. These descriptive signals support hypotheses for review.\n"
            + json.dumps(packet, ensure_ascii=True, separators=(",", ":")))
