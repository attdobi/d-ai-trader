"""Score live strategy exits using owned order IDs and settled Schwab activity.

An order acknowledgement can precede a posted cash transaction. Pending exits
remain separate from scored outcomes; later trader cycles retry the read-only
broker lookup. Broker-reported position basis is retained only for comparison.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from itertools import groupby
from zoneinfo import ZoneInfo

from sqlalchemy import text

from broker_fill_evidence import transaction_fills
from feedback_metrics import categorize_outcome


DDL = """
CREATE TABLE IF NOT EXISTS strategy_exit_accounting (
    config_hash TEXT NOT NULL,
    exit_order_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    held_before DOUBLE PRECISION NOT NULL,
    broker_basis DOUBLE PRECISION,
    entry_reason TEXT,
    exit_reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    detail TEXT NOT NULL DEFAULT 'awaiting broker activity',
    last_checked_at TIMESTAMP,
    confirmed_qty DOUBLE PRECISION NOT NULL DEFAULT 0,
    fill_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    outcome_id INTEGER,
    PRIMARY KEY (config_hash, exit_order_id)
)
"""


def queue_exit(conn, cfg, ticker, decision, holding):
    """Called after submission, before mutating the local book."""
    if not decision.get("order_id"):
        return
    conn.execute(text(DDL))
    conn.execute(text("""
        INSERT INTO strategy_exit_accounting
          (config_hash,exit_order_id,ticker,observed_at,held_before,broker_basis,
           entry_reason,exit_reason,confirmed_qty,fill_confirmed)
        VALUES (:cfg,:order_id,:ticker,:at,:shares,:basis,:entry,:reason,:qty,:confirmed)
        ON CONFLICT (config_hash,exit_order_id) DO NOTHING
    """), dict(cfg=cfg, order_id=str(decision["order_id"]), ticker=ticker, at=datetime.utcnow(),
               shares=float(holding.shares) if holding else 0, basis=holding.purchase_price if holding else None,
               entry=(holding.reason or "") if holding else "",
               reason=decision.get("reason") or "", qty=decision.get("executed_shares") or 0,
               confirmed=decision.get("execution_status") in {"filled", "partial_fill", "filled_details_pending"}))


def _decimal(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("invalid broker quantity or cost") from None
    if not amount.is_finite():
        raise ValueError("non-finite broker quantity or cost")
    return amount


def _open_inventory(fills, owned_orders, shares):
    """Walk back from verified inventory to a flat balance, then roll the owned net costs forward."""
    position = _decimal(shares)
    if position <= 0:
        raise ValueError("no confirmed long position")
    start = len(fills)
    while position > 0 and start:
        start -= 1
        f = fills[start]
        action = 'buy' if f['quantity'] > 0 else 'sell'
        if owned_orders.get(f['order_id']) != action:
            raise ValueError("campaign includes an unmatched broker order")
        position -= _decimal(f['quantity'])
    if position != 0:
        raise ValueError("strategy entry quantity is unverified")
    if start < len(fills) and start and fills[start - 1]['order_id'] == fills[start]['order_id']:
        raise ValueError("entry history starts inside a broker order")

    gross_basis = Decimal(0)
    net_basis = Decimal(0)
    entries = []
    history = fills[start:]
    if any(left['at'] == right['at'] and left['order_id'] != right['order_id']
           for left, right in zip(history, history[1:])):
        raise ValueError("simultaneous campaign orders require lot review")
    seen_orders = set()
    for order_id, group in groupby(history, key=lambda f: f['order_id']):
        if order_id in seen_orders:
            raise ValueError("interleaved entry history requires lot review")
        seen_orders.add(order_id)
        legs = list(group)
        qty = sum(_decimal(f['quantity']) for f in legs)
        if qty > 0:
            net_basis -= sum(_decimal(f['net_amount']) for f in legs)
            gross_basis += sum(_decimal(f['quantity']) * _decimal(f['price']) for f in legs)
            entries.append(order_id)
        else:
            if position + qty <= 0:
                raise ValueError("inconsistent campaign inventory")
            # Allocate cents once per exit and carry the remaining cents forward.
            net_basis -= (net_basis * -qty / position).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            gross_basis *= (position + qty) / position
        position += qty
    if net_basis <= 0:
        raise ValueError("invalid open strategy cost")
    return position, gross_basis, net_basis, entries, history[0]['at']


def campaign(fills, owned_orders, exit_order_id, held_before, executed_qty):
    """Match backward to a flat position; roll proportional net entry cost forward.

    Reject incomplete histories and external buys/sells in the matched campaign.
    Multiple posted activities for one order include their own net cash and fees.
    """
    exit_order_id = str(exit_order_id)
    if owned_orders.get(exit_order_id) != 'sell':
        raise ValueError("exit order is not linked to a strategy decision")
    fills = list(fills)
    indices = [i for i, f in enumerate(fills) if f['order_id'] == exit_order_id]
    if not indices:
        raise ValueError("exit cash transaction pending")
    if indices != list(range(indices[0], indices[-1] + 1)):
        raise ValueError("interleaved exit activities require lot review")
    exits = fills[indices[0]:indices[-1]+1]
    sold = -sum(_decimal(f['quantity']) for f in exits)
    position = _decimal(held_before)
    if (any(_decimal(f['quantity']) >= 0 for f in exits)
            or sold != _decimal(executed_qty) or sold <= 0 or sold > position):
        raise ValueError("posted exit quantity does not match broker position and fills")
    # Timestamp ties with independent orders cannot establish lot ownership.
    if any(exits[0]['at'] <= f['at'] <= exits[-1]['at'] and f['order_id'] != exit_order_id for f in fills):
        raise ValueError("simultaneous orders require lot review")
    position, gross_basis, net_basis, entries, first_entry = _open_inventory(
        fills[:indices[0]], owned_orders, held_before)
    entry_net_cost = (net_basis * sold / position).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    proceeds = sum(_decimal(f['net_amount']) for f in exits)
    if entry_net_cost <= 0 or proceeds <= 0:
        raise ValueError("invalid campaign cash amounts")
    profit = proceeds - entry_net_cost
    return dict(shares=float(sold), purchase_price=float(gross_basis / position),
                sell_price=float(sum(-_decimal(f['quantity']) * _decimal(f['price']) for f in exits) / sold),
                gain_loss_amount=float(profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                gain_loss_percentage=float(profit / entry_net_cost),
                first_entry=first_entry, sold_at=exits[-1]['at'], source="schwab_transactions",
                entry_order_ids=entries, exit_order_id=exit_order_id, entry_net_cost=float(entry_net_cost),
                exit_net_proceeds=float(proceeds))


def _owned_orders(conn, cfg, since):
    owned = {}
    confirmed = {}
    decision_ids = {}
    # Timestamps in trade_decisions are naive Pacific. Include the boundary
    # calendar day and use exact broker order IDs for the actual match.
    for row_id, at, value in conn.execute(text("""
        SELECT id, timestamp, data FROM trade_decisions WHERE config_hash=:cfg AND timestamp>=:since
    """), dict(cfg=cfg, since=since)):
        if isinstance(at, str):
            at = datetime.fromisoformat(at)
        if at.tzinfo is None:
            at = at.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
        try:
            rows = json.loads(value) if isinstance(value, str) else value
        except ValueError:
            continue  # A malformed historical payload cannot establish ownership.
        if isinstance(rows, dict):
            rows = rows.get('decisions')
        for row in rows or []:
            if isinstance(row, dict) and row.get('ticker') and row.get('order_id'):
                ticker = str(row['ticker']).upper()
                order_id = str(row['order_id'])
                ids = decision_ids.setdefault((ticker, order_id), set())
                repeated = bool(ids)
                ids.add(row_id)
                actions = owned.setdefault(ticker, {})
                action = str(row.get('action')).lower()
                actions[order_id] = "ambiguous" if repeated else action
                filled = row.get("executed_shares") or 0
                if filled or row.get("execution_status") in {"filled", "partial_fill", "filled_details_pending"}:
                    try:
                        quantity = _decimal(filled)
                    except ValueError:
                        actions[order_id] = "ambiguous"
                        quantity = Decimal(0)
                    confirmed.setdefault(ticker, []).append((order_id, at, quantity))
    return owned, confirmed, decision_ids


def _broker_activity(broker):
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=59)
    response = broker.client.get_transactions(broker.account_hash, start_date=since, end_date=now)
    if response.status_code != 200:
        raise ValueError("broker transactions unavailable")
    activities = response.json()
    if not isinstance(activities, list):
        raise ValueError("invalid broker transaction response")
    return since, activities, broker.get_positions()


def _position_quantity(positions, ticker):
    if positions is None:
        raise ValueError("broker positions unavailable")
    matches = [pos for pos in positions if (pos.get('instrument') or {}).get('symbol') == ticker]
    if len(matches) > 1 or any(pos.get('longQuantity') is None or _decimal(pos.get('shortQuantity') or 0)
                               for pos in matches):
        raise ValueError("ambiguous broker position")
    return _decimal(matches[0]['longQuantity']) if matches else Decimal(0)


def verified_open_costs(engine, cfg, broker, holdings):
    """Return per-share net costs for strategy-owned positions matching the decision snapshot."""
    if not holdings or not broker.ensure_authenticated():
        return {}
    since, activities, positions = _broker_activity(broker)
    with engine.connect() as conn:
        owned, confirmed, _ = _owned_orders(conn, cfg, since.replace(tzinfo=None) - timedelta(days=1))
    costs = {}
    for holding in holdings:
        ticker = holding['ticker']
        try:
            shares = _position_quantity(positions, ticker)
            if shares <= 0 or shares != _decimal(holding['shares']):
                continue
            fills = transaction_fills(activities, ticker)
            _, _, net, _, first = _open_inventory(fills, owned.get(ticker, {}), shares)
            posted = {}
            for f in fills:
                key = f['order_id']
                posted[key] = posted.get(key, Decimal(0)) + abs(_decimal(f['quantity']))
            # A closed-and-reopened campaign can have the same share count while
            # both new activities are still pending. Include same-day receipts
            # placed before the first posted fill to catch that ambiguity.
            if any(order_id not in posted or qty > posted[order_id]
                   for order_id, at, qty in confirmed.get(ticker, [])
                   if at >= first - timedelta(days=1)):
                continue
            costs[ticker] = float(net / shares)
        except (ValueError, ArithmeticError):
            continue
    return costs


def _write_score(conn, cfg, row, score):
    info = {key: score[key] for key in ('source', 'entry_order_ids', 'exit_order_id', 'entry_net_cost', 'exit_net_proceeds')}
    info['broker_basis'] = row['broker_basis']
    sold = score['sold_at'].astimezone(timezone.utc).replace(tzinfo=None)
    params = dict(score, cfg=cfg, ticker=row['ticker'], at=sold,
                  days=(score['sold_at'] - score['first_entry']).days,
                  reason=row['entry_reason'], exit_reason=row['exit_reason'],
                  category=categorize_outcome(score['gain_loss_amount'], score['gain_loss_percentage']),
                  context=json.dumps({'strategy_execution': info}))
    return conn.execute(text("""
        INSERT INTO trade_outcomes(config_hash,ticker,sell_timestamp,purchase_price,sell_price,shares,
            gain_loss_amount,gain_loss_percentage,hold_duration_days,original_reason,sell_reason,outcome_category,market_context)
        VALUES (:cfg,:ticker,:at,:purchase_price,:sell_price,:shares,:gain_loss_amount,:gain_loss_percentage,
            :days,:reason,:exit_reason,:category,:context) RETURNING id
    """), params).scalar_one()


def _complete_exit_receipt(conn, row_ids, cfg, ticker, score, terminal_status):
    """Attach final fills only to the saved SELL with this exact broker order ID."""
    fields = dict(executed_shares=score['shares'], executed_price=score['sell_price'],
                  executed_amount=round(score['shares'] * score['sell_price'], 2),
                  execution_status="filled" if terminal_status == "FILLED" else "partial_fill")
    lock = ' FOR UPDATE' if conn.dialect.name == 'postgresql' else ''
    for row_id in sorted(row_ids):
        key = {'id': row_id, 'cfg': cfg}
        data = conn.execute(text("SELECT data FROM trade_decisions WHERE id=:id AND config_hash=:cfg" + lock), key).scalar_one()
        data = json.loads(data) if isinstance(data, str) else data
        rows = data.get('decisions', []) if isinstance(data, dict) else data
        changed = False
        for d in rows or []:
            if not isinstance(d, dict) or str(d.get('ticker')).upper() != ticker or str(d.get('action')).lower() != 'sell':
                continue
            if str(d.get('order_id')) != score['exit_order_id']:
                continue
            if any(d.get(k) != v for k, v in fields.items()) or d.get('execution_error'):
                d.setdefault('initial_execution_receipt', {k:d[k] for k in (*fields, 'execution_error') if k in d})
            d.update(fields)
            d['execution_evidence_source'] = 'schwab_transactions'
            d.pop('execution_error', None)
            changed = True
        if changed:
            conn.execute(text("UPDATE trade_decisions SET data=:data WHERE id=:id AND config_hash=:cfg"),
                         dict(key, data=json.dumps(data)))


def reconcile(engine, cfg, broker):
    """Read-only broker calls. Row locks make local score insertion retry-safe."""
    with engine.begin() as conn:
        conn.execute(text(DDL))
        pending = conn.execute(text("""
            SELECT * FROM strategy_exit_accounting WHERE config_hash=:h AND status='pending'
            ORDER BY CASE WHEN last_checked_at IS NULL THEN 0 ELSE 1 END, last_checked_at, observed_at
            LIMIT 12
        """), {'h': cfg}).mappings().all()
    if not pending or not broker.ensure_authenticated():
        return
    now = datetime.now(timezone.utc)
    since, activities, positions = _broker_activity(broker)
    with engine.connect() as conn:
        known, _, decision_ids = _owned_orders(conn, cfg, since.replace(tzinfo=None) - timedelta(days=1))
    for row in pending:
        key = dict(cfg=cfg, order_id=row['exit_order_id'])
        score = None
        state = 'pending'
        qty = row['confirmed_qty']
        confirmed = bool(row['fill_confirmed'] or qty)
        try:
            observed = row['observed_at']
            if isinstance(observed, str):
                observed = datetime.fromisoformat(observed)
            if observed < since.replace(tzinfo=None):
                state = 'unscored'
                raise ValueError("outside broker activity lookback")
            order = broker.get_order_status(row['exit_order_id']) or {}
            status = str(order.get("status") or "").upper()
            confirmed = confirmed or status == 'FILLED'
            # A partially filled working order must enter the re-entry quarantine.
            # Preserve previously confirmed shares during a temporary lookup gap.
            if order.get("filledQuantity") is not None:
                qty = max(float(qty), float(order["filledQuantity"]))
            if status not in broker._TERMINAL_ORDER_STATES:
                raise ValueError("awaiting final broker order status")
            if not qty and order.get("filledQuantity") is not None and status in {'REJECTED','CANCELED','EXPIRED','REPLACED'}:
                state = 'unfilled'
                raise ValueError("terminal broker order without fills")
            owned = known.get(row['ticker'], {})
            fills = transaction_fills(activities, row['ticker'])
            exit_legs = [f for f in fills if f['order_id'] == row['exit_order_id']]
            if not exit_legs:
                raise ValueError("exit cash transaction pending")
            current = _position_quantity(positions, row['ticker'])
            subsequent = sum(Decimal(str(f['quantity'])) for f in fills if f['at'] >= exit_legs[0]['at'])
            if current - subsequent != Decimal(str(row['held_before'])):
                raise ValueError("pre-exit inventory does not reconcile to broker position and activity")
            score = campaign(fills, owned, row['exit_order_id'], row['held_before'], qty)
            state, detail = 'scored', 'matched broker cash transactions'
        except (ValueError, ArithmeticError) as exc:
            detail = str(exc)
        with engine.begin() as conn:
            # Recheck under lock to avoid scoring twice across dashboard and trader workers.
            suffix = ' FOR UPDATE' if conn.dialect.name == 'postgresql' else ''
            locked = conn.execute(text("SELECT status,confirmed_qty,fill_confirmed FROM strategy_exit_accounting "
                                       "WHERE config_hash=:cfg AND exit_order_id=:order_id" + suffix), key).first()
            if not locked or locked.status != 'pending':
                continue
            if ((state == 'unfilled' and (locked.confirmed_qty or locked.fill_confirmed))
                    or (score and score['shares'] < locked.confirmed_qty)):
                score = None
                state, detail = 'pending', 'conflicting broker fill evidence'
            outcome = _write_score(conn, cfg, row, score) if score else None
            if score:
                _complete_exit_receipt(conn, decision_ids.get((row['ticker'], row['exit_order_id']), ()),
                                       cfg, row['ticker'], score, status)
            conn.execute(text("""
                UPDATE strategy_exit_accounting SET status=:state,detail=:detail,
                    confirmed_qty=CASE WHEN confirmed_qty>:qty THEN confirmed_qty ELSE :qty END,
                    fill_confirmed=fill_confirmed OR :confirmed,
                    outcome_id=:outcome,last_checked_at=:checked
                WHERE config_hash=:cfg AND exit_order_id=:order_id
            """), dict(key, outcome=outcome, state=state, detail=detail, qty=qty,
                       confirmed=bool(confirmed or qty), checked=now.replace(tzinfo=None)))
