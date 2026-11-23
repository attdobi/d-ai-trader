from datetime import timedelta

import pytest

from broker_fill_evidence import transaction_fills


def trade(symbol="ACME", **overrides):
    row = {
        "type": "TRADE", "status": "VALID", "time": "2026-11-23T14:35:10+0000",
        "orderId": 8, "activityId": 7, "netAmount": 29.99,
        "transferItems": [
            {"instrument": {"symbol": symbol, "assetType": "EQUITY"}, "amount": -2, "price": 15},
            {"instrument": {"assetType": "CURRENCY"}, "feeType": "SEC_FEE", "cost": -0.01},
        ],
    }
    return {**row, **overrides}


def test_preserves_reported_net_including_fees_and_deduplicates_activities():
    row = trade()
    fills = transaction_fills([row, trade("OTHER", activityId=12), trade(None, activityId=13), row], "ACME")
    assert len(fills) == 1
    assert (fills[0]["order_id"], fills[0]["quantity"], fills[0]["net_amount"]) == ("8", -2, 29.99)
    assert fills[0]["at"].utcoffset() == timedelta(0)
    with pytest.raises(ValueError, match="Conflicting"):
        transaction_fills([row, trade(netAmount=29.98)], "ACME")


def test_ambiguous_fee_allocation_and_unverifiable_movements_cannot_score():
    row = trade()
    row["transferItems"].append(trade("OTHER")["transferItems"][0])
    for malformed in [row, trade(netAmount=0), trade(activityId=""), trade(status="PENDING"),
                      trade(type="JOURNAL"), trade(time="2026-11-23T14:35:10")]:
        with pytest.raises(ValueError):
            transaction_fills([malformed], "ACME")


def test_multiple_same_side_legs_use_execution_vwap():
    row = trade(netAmount=61.99)
    row["transferItems"].append({**row["transferItems"][0], "price": 16})
    fill, = transaction_fills([row], "ACME")
    assert fill["price"] == 15.5
    assert fill["quantity"] == -4
