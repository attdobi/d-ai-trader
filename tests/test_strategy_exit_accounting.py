"""No-order coverage for the transition from a broker receipt to a scored exit."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from strategy_exit_accounting import campaign, queue_exit, reconcile


def fill(order_id, hour, qty, price, net):
    return dict(order_id=order_id, at=datetime.now(timezone.utc).replace(microsecond=0)
                - timedelta(days=1) + timedelta(minutes=hour),
                quantity=qty, price=price, net_amount=net)


def test_partial_exit_uses_proportional_owned_net_cost():
    facts = [fill('b', 0, 5, 100, -500.05), fill('s1', 1, -2, 90, 179.98),
             fill('b2', 2, 2, 120, -240.02), fill('s2', 3, -4, 108, 431.96)]
    owned = {'b':'buy', 's1':'sell', 'b2':'buy', 's2':'sell'}
    result = campaign(facts, owned, 's2', 5, 4)
    assert result['purchase_price'] == 108
    assert result['entry_net_cost'] == pytest.approx(432.04)
    assert result['gain_loss_amount'] == -.08
    for bad_orders in ({'s2':'sell'}, {**owned,'s1':'buy'}, {**owned,'s2':'buy'}):
        with pytest.raises(ValueError):
            campaign(facts, bad_orders, 's2', 5, 4)
    for before, qty in [(6,4), (5,3), (3,4)]:
        with pytest.raises(ValueError):
            campaign(facts, owned, 's2', before, qty)


def test_settled_activity_replaces_pending_once_and_keeps_tax_basis_separate():
    engine = create_engine('sqlite://')
    holdings = SimpleNamespace(shares=3, purchase_price=47.25, reason='strategy')
    exits = dict(order_id='s', executed_shares=3, reason='exit')
    now = datetime.now(timezone.utc)
    facts = [fill('b', 0, 3, 43.50, -130.50), fill('s', 2, -3, 41.25, 123.73)]
    rows = []
    orders = []
    for f in facts:
        orders.append(dict(order_id=f['order_id'], ticker='XYZ', action='buy' if f['quantity'] > 0 else 'sell'))
        rows.append(dict(orderId=f['order_id'],activityId=f['order_id'],time=f['at'].isoformat(),
                         netAmount=f['net_amount'],type='TRADE',status='VALID',
                         transferItems=[dict(instrument=dict(assetType='EQUITY',symbol='XYZ'),
                                             amount=f['quantity'],price=f['price'])]))
    orders[-1].update(execution_status="filled_details_pending", total_value=145, shares=3)
    postings = rows[:1]
    broker = SimpleNamespace(ensure_authenticated=lambda:True, get_positions=lambda:[], account_hash='test', _TERMINAL_ORDER_STATES={'FILLED'},
        client=SimpleNamespace(get_transactions=lambda *a,**kw: SimpleNamespace(status_code=200,json=lambda:postings)),
        get_order_status=lambda order_id:{'status':'FILLED','filledQuantity':3})
    with engine.begin() as c:
        c.execute(text("CREATE TABLE trade_decisions(id INTEGER PRIMARY KEY,config_hash TEXT,timestamp TIMESTAMP,data TEXT)"))
        c.execute(text("INSERT INTO trade_decisions(config_hash,timestamp,data) VALUES ('c',:ts,:data)"),
                  dict(ts=now.replace(tzinfo=None),data=json.dumps(orders)))
        c.execute(text("""
          CREATE TABLE trade_outcomes(id INTEGER PRIMARY KEY,config_hash TEXT,ticker TEXT,sell_timestamp TIMESTAMP,
            purchase_price REAL,sell_price REAL,shares REAL,gain_loss_amount REAL,gain_loss_percentage REAL,
            hold_duration_days INTEGER,original_reason TEXT,sell_reason TEXT,outcome_category TEXT,market_context TEXT)
        """))
        queue_exit(c, 'c', 'XYZ', exits, holdings)
        queue_exit(c, 'c', 'XYZ', exits, holdings)
    reconcile(engine,'c',broker)
    with engine.connect() as c:
        assert c.execute(text("SELECT status,confirmed_qty FROM strategy_exit_accounting")).first()==('pending',3)
        assert not c.execute(text("SELECT * FROM trade_outcomes")).first()
    postings.extend(rows[1:])
    broker.get_positions = lambda: [{"instrument": {"symbol": "XYZ"}, "longQuantity": 1}]
    reconcile(engine,'c',broker)
    with engine.connect() as c:
        assert c.execute(text("SELECT status FROM strategy_exit_accounting")).scalar_one() == "pending"
        assert not c.execute(text("SELECT * FROM trade_outcomes")).first()
    broker.get_positions = lambda: []
    reconcile(engine,'c',broker)
    reconcile(engine,'c',broker)
    with engine.connect() as c:
        assert c.execute(text("SELECT status,outcome_id FROM strategy_exit_accounting")).one()==('scored',1)
        result = c.execute(text("SELECT * FROM trade_outcomes")).mappings().one()
        assert result['purchase_price']==43.50 and result['gain_loss_amount']==-6.77
        buy, sell = json.loads(c.execute(text("SELECT data FROM trade_decisions")).scalar_one())
        assert "executed_price" not in buy
        assert sell["execution_status"] == "filled" and sell["executed_price"] == 41.25
        assert sell["total_value"] == 145 and sell["executed_amount"] == 123.75
        assert sell["initial_execution_receipt"] == {"execution_status": "filled_details_pending"}
        assert result['gain_loss_percentage']==pytest.approx(-6.77/130.50)
        assert json.loads(result['market_context'])['strategy_execution']['broker_basis']==47.25


def test_open_cost_is_available_only_for_matching_owned_inventory():
    from strategy_exit_accounting import verified_open_costs
    engine = create_engine("sqlite://")
    now = datetime.now(timezone.utc)
    rows, receipts, positions, holdings = [], [], [], []
    for symbol, broker_qty, stored_qty in [('OWNED',3,3), ('MIXED',3,3), ('MISSING',4,4),
                                           ('STALE',4,3), ('LAG',3,3)]:
        holdings.append(dict(ticker=symbol, shares=stored_qty,purchase_price=70))
        positions.append(dict(instrument=dict(symbol=symbol),longQuantity=broker_qty))
        qty = 2 if symbol == 'MIXED' else 3
        oid = symbol + '-buy'
        receipts.append(dict(ticker=symbol,action='buy',order_id=oid,execution_status='filled',executed_shares=qty))
        rows.append(dict(orderId=oid,activityId=oid,time=(now-timedelta(hours=2)).isoformat(),
                         type="TRADE",status="VALID",netAmount=-qty*50-.03,
                         transferItems=[dict(instrument=dict(symbol=symbol,assetType="EQUITY"),amount=qty,price=50)]))
        if symbol == 'MIXED':
            rows.append(dict(orderId='external',activityId='manual',time=(now-timedelta(hours=1)).isoformat(),
                             type="TRADE",status="VALID",netAmount=-58.00,
                             transferItems=[dict(instrument=dict(symbol=symbol,assetType="EQUITY"),amount=1,price=58)]))
        if symbol == 'LAG':
            receipts.append(dict(ticker=symbol,action='sell',order_id='exit-not-yet-posted',
                                 execution_status='filled_details_pending'))
    with engine.begin() as c:
        c.execute(text("CREATE TABLE trade_decisions(id INTEGER PRIMARY KEY,config_hash TEXT,timestamp TIMESTAMP,data TEXT)"))
        c.execute(text("INSERT INTO trade_decisions(config_hash,timestamp,data) VALUES ('c',:at,:data)"),
                  dict(at=now.replace(tzinfo=None),data=json.dumps(receipts)))
    broker=SimpleNamespace(ensure_authenticated=lambda:True,get_positions=lambda:positions,account_hash='test',
        client=SimpleNamespace(get_transactions=lambda *a,**kw:SimpleNamespace(status_code=200,json=lambda:rows)))
    assert verified_open_costs(engine,'c',broker,holdings) == {'OWNED': 50.01}
    assert holdings[0]['purchase_price']==70
