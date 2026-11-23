"""Matched close-to-next-open paper observations for supplied large selloffs."""
import json
from datetime import datetime, time, timedelta

from sqlalchemy import bindparam, text

from feedback_metrics import reporting_table_exists

from . import opportunities as opp
from .citations import normalize_ids, parse_cites, strip_cites
from .model import ID_RE
from .selloff_policy import MIN_DECLINE_PCT, MIN_DOLLAR_VOLUME, SELLOFF_REVIEW_HEADER, SELLOFF_REVIEW_ID

SPEC_ID = "liquid_selloff_close_next_open_v1"
# Published NYSE 13:00 ET regular-session closes within the configured holiday calendar.
EARLY_CLOSES = {"2026-11-27", "2026-12-24", "2027-11-26"}
DDL = """
CREATE TABLE IF NOT EXISTS learning_selloff_observations (
 opportunity_id INTEGER PRIMARY KEY REFERENCES learning_opportunities(id),
 spec_id TEXT NOT NULL, origin TEXT NOT NULL, day_pct DOUBLE PRECISION NOT NULL,
 observed_price DOUBLE PRECISION NOT NULL, session_volume DOUBLE PRECISION NOT NULL,
 quarantined BOOLEAN NOT NULL, reviewed_at TEXT, assessment TEXT, status TEXT NOT NULL DEFAULT 'pending',
 measured_at TEXT, entry_close DOUBLE PRECISION, exit_open DOUBLE PRECISION, net_return_pct DOUBLE PRECISION
)
"""


def select_candidates(momentum, context, observed_at, *, reconstructed=False):
    """Select using only the supplied context and momentum available at observation time."""
    from event_calendar import NYSE_HOLIDAYS
    now = opp._now(observed_at).astimezone(opp.ET)
    day = now.date().isoformat()
    close = time(13) if day in EARLY_CLOSES else time(16)
    if (now.year not in NYSE_HOLIDAYS or day in NYSE_HOLIDAYS[now.year] or now.weekday() >= 5
            or not time(9, 30) <= now.time() < close):
        return []
    if not isinstance(context, dict) or not all(isinstance(context.get(k), (list, tuple))
                                               for k in ("trend", "holdings", "quarantined")):
        return []
    allowed = set(context["trend"]) - set(context["holdings"])
    results = {}
    for row in momentum or ():
        if not isinstance(row, dict):
            continue
        symbol = opp._ticker(row.get("symbol"))
        price, volume, change = opp._positive(row.get("price")), opp._positive(row.get("volume")), opp._number(row.get("daily_pct"))
        if symbol not in allowed or not price or not volume or change is None:
            continue
        if change > -MIN_DECLINE_PCT or change <= -100 or price * volume < MIN_DOLLAR_VOLUME:
            continue
        if not reconstructed or row.get("price_asof") is not None:
            try:
                quote = opp._now(row["price_asof"]).astimezone(opp.ET) if row.get("price_asof") else None
            except (TypeError, ValueError):
                continue
            if (quote is None or row.get("volume_session") != day or quote.date() != now.date()
                    or quote.time() < time(9, 30) or not timedelta() <= now - quote <= timedelta(minutes=30)):
                continue
        results[symbol] = dict(ticker=symbol, price=price, volume=volume, day_pct=change,
                               quarantined=symbol in context["quarantined"])
    return [results[s] for s in sorted(results)]


def prompt_section(candidates):
    if not candidates:
        return ""
    lines = ["", SELLOFF_REVIEW_HEADER]
    for c in candidates:
        status = " · re-entry quarantine" if c["quarantined"] else ""
        lines.append(f"- {c['ticker']} · {c['day_pct']:+.1f}% vs previous close · observed ${c['price']:.2f}{status}")
    return "\n".join(lines) + "\n"


def attach(conn, config_hash, run_id, input_id, candidates, observed_at, origin):
    count = 0
    for c in candidates:
        result = conn.execute(text("""INSERT INTO learning_selloff_observations
            (opportunity_id,spec_id,origin,day_pct,observed_price,session_volume,quarantined)
            SELECT id,:spec,:origin,:day_pct,:price,:volume,:quarantined FROM learning_opportunities
            WHERE config_hash=:h AND run_id=:r AND ticker=:ticker AND observed_at=:t
            AND coverage IN ('prospective_context','prospective_screener')
            AND (input_id=:i OR (input_id IS NULL AND :no_id))
            ON CONFLICT(opportunity_id) DO NOTHING"""),
            {**c, "h": config_hash, "r": str(run_id), "i": input_id, "no_id": input_id is None,
             "spec": SPEC_ID, "origin": origin, "t": observed_at})
        count += result.rowcount
    return count


def record_review(conn, config_hash, run_id, input_id, reply, reviewed_at, origin):
    """Freeze even omissions on the first valid response and keep WATCH distinct from reject."""
    if isinstance(reply, str):
        try:
            reply = json.loads(reply)
        except ValueError:
            return
    if isinstance(reply, list):
        decisions, considered = reply, []
    elif isinstance(reply, dict) and isinstance(reply.get("decisions"), list) and not reply.get("error"):
        decisions, considered = reply["decisions"], reply.get("considered", [])
    else:
        return
    verdicts = {}
    for item in considered if isinstance(considered, list) else []:
        if not isinstance(item, dict):
            continue
        ticker = opp._ticker(item.get("ticker"))
        verb = str(item.get("verdict", "")).strip().lower()
        if verb == "watch":
            verdicts[ticker] = "WATCH"
        elif verb in opp.REJECT_VERDICTS:
            verdicts[ticker] = "PASS"
        elif verb == "buy":
            verdicts[ticker] = "BUY_CONSIDERED"
    for item in decisions:
        if isinstance(item, dict):
            action = str(item.get("action", "")).strip().upper()
            if action in ("BUY", "HOLD", "SELL"):
                verdicts[opp._ticker(item.get("ticker"))] = action
    pending = conn.execute(text("""SELECT p.id,p.ticker FROM learning_opportunities p
        JOIN learning_selloff_observations s ON s.opportunity_id=p.id
        WHERE p.config_hash=:h AND p.run_id=:r AND s.reviewed_at IS NULL AND s.origin=:origin
        AND (p.input_id=:i OR (p.input_id IS NULL AND :no_id))"""),
        dict(h=config_hash,r=str(run_id),i=input_id,no_id=input_id is None,origin=origin)).mappings().all()
    for p in pending:
        conn.execute(text("""UPDATE learning_selloff_observations SET reviewed_at=:t,assessment=:a
            WHERE opportunity_id=:id AND reviewed_at IS NULL"""),
            dict(t=reviewed_at,a=verdicts.get(p["ticker"], "NOT_ASSESSED"),id=p["id"]))


def mark(conn, case, bars, now):
    dates = opp._dates(case, 1)
    status, entry, exit_price, net = "pending", None, None, None
    if not dates:
        status = "calendar_unknown"
    elif now.astimezone(opp.ET) >= datetime.combine(dates[0], time(9, 31), tzinfo=opp.ET):
        prices = {str(b.get("date"))[:10]: b for b in bars if isinstance(b, dict) and b.get("adjusted") is True}
        entry = opp._positive(prices.get(case["session_date"], {}).get("close"))
        exit_price = opp._positive(prices.get(dates[0].isoformat(), {}).get("open"))
        status = "missing_data"
        if entry and exit_price:
            side = opp.SIDE_COST_BPS / 10000
            net = 100 * (exit_price * (1 - side) / (entry * (1 + side)) - 1)
            status = "matured"
    conn.execute(text("""UPDATE learning_selloff_observations SET status=:s, measured_at=:t,
        entry_close=:entry, exit_open=:exit, net_return_pct=:net
        WHERE opportunity_id=:i AND spec_id=:spec AND status<>'matured'"""),
        dict(s=status,t=now.isoformat(),entry=entry,exit=exit_price,net=net,i=case["id"],spec=SPEC_ID))


def _archived_indices(conn, config_hash, input_ids):
    """Read only the index shipped with each linked Decider input, including its policy version."""
    if not input_ids or not reporting_table_exists(conn, "decider_inputs"):
        return {}
    query = text("""SELECT id,run_id,prompt_version,user_prompt FROM decider_inputs
        WHERE config_hash=:h AND call_kind='decide' AND id IN :ids""").bindparams(bindparam("ids", expanding=True))
    indices = {}
    for row in conn.execute(query, {"h":config_hash, "ids":sorted(input_ids)}).mappings():
        prompt = row["user_prompt"] or ""
        header = "GUIDELINE INDEX (id — title):\n"
        ids = set()
        if prompt.count(header) == 1:
            for line in prompt.partition(header)[2].splitlines():
                node, sep, _ = line.partition(" — ")
                if not sep or not node.startswith("DA.") or not ID_RE.fullmatch(node):
                    break
                ids.add(node)
        indices[row["id"]] = (row["run_id"], row["prompt_version"], ids)
    return indices


def report(conn, config_hash, start, end):
    if not reporting_table_exists(conn, "learning_selloff_observations"):
        return {"status": "unavailable", "rows": [], "recent": []}
    records = conn.execute(text("""SELECT * FROM (
        SELECT p.ticker,p.session_date,p.run_id,p.input_id,p.prompt_version,p.observed_at,
        p.action,p.action_recorded_at,p.reason,p.cited_json,s.*,
        ROW_NUMBER() OVER (PARTITION BY s.origin,p.session_date,p.ticker ORDER BY p.observed_at,p.id) AS seq
        FROM learning_opportunities p JOIN learning_selloff_observations s ON s.opportunity_id=p.id
        WHERE p.config_hash=:h AND s.spec_id=:spec AND p.observed_at<=:end AND p.session_date>=:day) ranked
        WHERE seq=1 AND observed_at>=:start ORDER BY observed_at DESC,ticker"""),
        dict(h=config_hash,spec=SPEC_ID,start=start.isoformat(),end=end.isoformat(),
             day=start.astimezone(opp.ET).date().isoformat())).mappings()
    groups, recent, evidence = {}, [], []
    cutoff = end.isoformat()
    for r in records:
        reviewed = r["reviewed_at"] and r["reviewed_at"] <= cutoff
        action = "NO_REPLY"
        if reviewed:
            action = r["assessment"] or "NOT_ASSESSED"
        key = (r["origin"], action)
        group = groups.setdefault(key, dict(origin=r["origin"], action=action, observations=0,
                    quarantined=0, matured=0, pending=0, missing=0, wins=0, net_sum=0.0))
        group["observations"] += 1
        group["quarantined"] += int(r["quarantined"])
        status = r["status"] if r["measured_at"] and r["measured_at"] <= cutoff else "pending"
        net = r["net_return_pct"] if status == "matured" else None
        if net is not None:
            group["matured"] += 1
            group["wins"] += int(net > 0)
            group["net_sum"] += net
        elif status == "pending":
            group["pending"] += 1
        else:
            group["missing"] += 1
        if len(recent) < 40:
            recent.append(dict(ticker=r["ticker"], session=r["session_date"], input_id=r["input_id"],
                origin=r["origin"], day_pct=round(r["day_pct"],2), quarantined=bool(r["quarantined"]),
                action=action, status=status, net_return_pct=round(net,3) if net is not None else None,
                reason="", cited=[], prompt_version=r["prompt_version"]))
            # The first opportunity action is immutable. Require the same first valid reply as
            # the selloff verdict; a later retry may have assessed an originally omitted ticker.
            expected = {"WATCH":"PASS", "BUY_CONSIDERED":"BUY"}.get(action,action)
            if (action not in ("NOT_ASSESSED", "NO_REPLY") and r["action"] == expected
                    and r["reviewed_at"] == r["action_recorded_at"]):
                reason = r["reason"] or ""
                clean = " ".join(strip_cites(reason).split())
                recent[-1]["reason"] = clean if len(clean) <= 360 else clean[:359].rstrip() + "…"
                try:
                    supplied = json.loads(r["cited_json"])
                except (TypeError, ValueError):
                    supplied = []
                cited = normalize_ids((supplied if isinstance(supplied, list) else []) + parse_cites(reason))
                if cited and r["input_id"] is not None and r["prompt_version"] is not None:
                    evidence.append((recent[-1],r["run_id"],cited))
    indices = _archived_indices(conn, config_hash, {row["input_id"] for row,_,_ in evidence})
    for row, run, cited in evidence:
        index = indices.get(row["input_id"])
        if index and (run, row["prompt_version"]) == index[:2]:
            row["cited"] = normalize_ids(cited, known=index[2])
    for g in groups.values():
        total = g.pop("net_sum")
        g["mean_net_pct"] = round(total/g["matured"], 3) if g["matured"] else None
    return {"status": "ok", "spec_id": SPEC_ID, "rows": [groups[k] for k in sorted(groups)], "recent": recent}


def backfill_selloffs(engine, config_hash, input_ids, *, apply=False):
    """Reconstruct only exact user-requested inputs with matching pre-call archived momentum."""
    ids = sorted({int(i) for i in input_ids})
    if not config_hash or not ids or len(ids) > 100:
        raise ValueError("Specify a configuration and 1–100 saved decision input IDs")
    if apply:
        opp.ensure_schema(engine)
    rows, skipped, inserted = [], {}, 0
    with engine.begin() as conn:
        for i in ids:
            params = {"h": config_hash, "i": i}
            d = conn.execute(text("""SELECT run_id,context_json,user_prompt,raw_reply FROM decider_inputs
                WHERE config_hash=:h AND id=:i AND call_kind='decide'"""),params).mappings().one_or_none()
            if not d:
                skipped[i] = "no matching decision"
                continue
            params["r"] = d["run_id"]
            cases = conn.execute(text("""SELECT ticker,observed_at,action_recorded_at FROM learning_opportunities
                WHERE config_hash=:h AND run_id=:r AND input_id=:i AND coverage IN
                ('prospective_context','prospective_screener')"""), params).mappings().all()
            times = {r["observed_at"] for r in cases}
            if len(times) != 1:
                skipped[i] = "missing or ambiguous pre-call snapshot"
                continue
            stamp = times.pop()
            observed = opp._now(stamp)
            snapshots = conn.execute(text("""SELECT momentum_data,momentum_summary,generated_at FROM momentum_snapshots
                WHERE config_hash=:h AND run_id=:r"""),params).mappings()
            matches = [s for s in snapshots if s["generated_at"] and s["momentum_summary"]
                       and s["momentum_summary"] in (d["user_prompt"] or "")
                       and timedelta() <= observed - opp._now(s["generated_at"]) <= timedelta(hours=1)]
            if len(matches) != 1:
                skipped[i] = "missing or ambiguous matching momentum"
                continue
            data = matches[0]["momentum_data"]
            context = d["context_json"]
            if isinstance(data, str):
                data = json.loads(data)
            if isinstance(context, str):
                context = json.loads(context)
            candidates = select_candidates(data, context, observed, reconstructed=True)
            seen = {r["ticker"] for r in cases}
            candidates = [c for c in candidates if c["ticker"] in seen]
            # Raw replies contain no original completion timestamp. Use a recorded action time or
            # the reconstruction time; missing replies always stay unknown.
            if apply:
                inserted += attach(conn,config_hash,d["run_id"],i,candidates,stamp,"reconstructed")
                reviewed = min((r["action_recorded_at"] for r in cases if r["action_recorded_at"]),
                               default=None) or opp._now().isoformat()
                record_review(conn, config_hash, d["run_id"], i, d["raw_reply"], reviewed, "reconstructed")
            rows.extend({"input_id":i, "ticker":c["ticker"], "day_pct":round(c["day_pct"],2),
                         "quarantined":c["quarantined"]} for c in candidates)
    return {"inputs":ids,"candidates":rows,"skipped":skipped,"inserted":inserted}
