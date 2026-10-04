"""Balanced prompt-review history window (shared/review_window.py).

Human-first ordering filled every slot with labeled rows, so an unclicked critic
verdict never reached the next generation/feedback prompt. The window keeps up to 5
human-labeled rows + up to 3 unlabeled genuine critic verdicts, fills to 8 by
recency and returns newest-first. Runs against an in-memory SQLite database.
"""

from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from shared.review_window import fetch_review_window, select_balanced
from tests.test_dashboard_imports import dashboard_server_module, isolated_policy_graph  # noqa: F401

CFG = "cfg_test"
T0 = datetime(2026, 9, 1, 12, 0, 0)


def _row(i, labeled, genuine=True):
    return {"_rid": i, "_labeled": 1 if labeled else 0, "_genuine": 1 if genuine else 0, "name": f"r{i}"}


def _names(rows):
    return [r["name"] for r in rows]


# ---------------------------------------------------------------- select_balanced


def test_all_labeled_history_still_admits_three_pending_critic_verdicts():
    # newest-first: 3 pending genuine verdicts are OLDER than 10 labeled rows
    rows = [_row(i, labeled=True) for i in range(10)] + [_row(10 + i, labeled=False) for i in range(3)]
    out = select_balanced(rows)
    assert _names(out) == ["r0", "r1", "r2", "r3", "r4", "r10", "r11", "r12"]


def test_fill_to_limit_by_recency_when_a_side_is_short():
    rows = [_row(0, labeled=False), _row(1, labeled=True), _row(2, labeled=True)] + \
           [_row(3 + i, labeled=True) for i in range(10)]
    out = select_balanced(rows)
    # 1 pending genuine + 5 labeled quota + 2 more labeled by recency, newest-first
    assert _names(out) == ["r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7"]
    assert len(out) == 8


def test_heuristic_auto_rows_never_take_a_critic_slot_but_can_fill():
    rows = [_row(0, labeled=False, genuine=False), _row(1, labeled=False, genuine=False)] + \
           [_row(2 + i, labeled=True) for i in range(5)] + [_row(7, labeled=False)]
    out = select_balanced(rows, limit=8)
    # quotas: r2..r6 (labeled) + r7 (genuine pending); fill: r0, r1
    assert _names(out) == ["r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7"]
    out = select_balanced(rows, limit=6)
    assert _names(out) == ["r2", "r3", "r4", "r5", "r6"] + ["r7"]


def test_window_returns_newest_first_and_respects_small_limits():
    rows = [_row(0, labeled=False), _row(1, labeled=True), _row(2, labeled=False)]
    assert _names(select_balanced(rows)) == ["r0", "r1", "r2"]
    assert _names(select_balanced(rows, limit=1)) == ["r1"]
    assert select_balanced([], limit=8) == []
    assert select_balanced(rows, limit=0) == []


def test_human_only_quota_reproduces_label_first_window():
    rows = [_row(0, labeled=False)] + [_row(1 + i, labeled=True) for i in range(12)]
    out = select_balanced(rows, limit=10, human_quota=10, critic_quota=0)
    assert _names(out) == [f"r{i}" for i in range(1, 11)]


# ------------------------------------------------------------ fetch_review_window


@pytest.fixture
def review_db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE prompt_change_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP,
                config_hash TEXT,
                agent_type TEXT NOT NULL,
                from_version INTEGER,
                to_version INTEGER,
                critic_verdict TEXT,
                critic_reason TEXT,
                critic_confidence REAL,
                critic_auto BOOLEAN,
                human_verdict TEXT,
                human_agrees_critic BOOLEAN,
                human_sections TEXT,
                realized_winrate_delta REAL,
                realized_pnl REAL
            )
        """))
    return engine


def _insert(engine, n, *, agent="DeciderAgent", human=None, conf=0.9, auto=False, cfg=CFG,
            agrees=None, sections=None, reason="r"):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO prompt_change_reviews
                (created_at, config_hash, agent_type, from_version, to_version, critic_verdict,
                 critic_reason, critic_confidence, critic_auto, human_verdict, human_agrees_critic,
                 human_sections)
            VALUES (:t, :h, :a, :v, :v2, 'reject', :reason, :c, :auto, :hv, :agrees, :sections)
        """), {"t": (T0 + timedelta(hours=n)).isoformat(sep=" "), "h": cfg, "a": agent, "v": n,
               "v2": n + 1, "reason": reason, "c": conf, "auto": auto, "hv": human,
               "agrees": agrees, "sections": sections})


def test_fetch_window_balances_labeled_and_pending_verdicts(review_db):
    for n in range(10, 22):                 # 12 newest rows all human-labeled
        _insert(review_db, n, human="approve")
    for n in range(1, 4):                   # 3 older unclicked genuine verdicts
        _insert(review_db, n)
    _insert(review_db, 5, conf=0.0)         # outage row: no judgment, never shown
    _insert(review_db, 30, cfg="other")     # other config
    with review_db.connect() as conn:
        rows = fetch_review_window(conn, CFG)
    assert [r["from_version"] for r in rows] == [21, 20, 19, 18, 17, 3, 2, 1]
    assert [r["human_verdict"] for r in rows][-3:] == [None, None, None]
    assert rows[0]["review_date"] == "2026-09-02" and rows[-1]["review_date"] == "2026-09-01"
    assert set(rows[0]) >= {"review_date", "agent_type", "from_version", "to_version", "critic_verdict",
                            "critic_auto", "critic_confidence", "critic_reason", "human_verdict",
                            "human_agrees_critic", "human_sections", "realized_winrate_delta",
                            "realized_pnl"}
    assert not any(k.startswith("_") for k in rows[0])


def test_fetch_window_filters_and_critic_track_record_mode(review_db):
    for n in range(1, 4):
        _insert(review_db, n, human="reject", agrees=True)
    _insert(review_db, 4, auto=True, conf=0.9)                 # heuristic auto-verdict
    _insert(review_db, 5)                                      # pending genuine
    _insert(review_db, 6, agent="SummarizerAgent", human="approve", agrees=False,
            sections='{"approved": ["memory"]}')
    _insert(review_db, 7, conf=0.0)                            # outage
    with review_db.connect() as conn:
        everything = fetch_review_window(conn, CFG)
        decider = fetch_review_window(conn, CFG, agent_type="DeciderAgent")
        genuine = fetch_review_window(conn, CFG, genuine_only=True)
        track = fetch_review_window(conn, CFG, genuine_only=True, limit=2, human_quota=2, critic_quota=0)
        short = fetch_review_window(conn, CFG, reason_chars=1)
    assert [r["from_version"] for r in everything] == [6, 5, 4, 3, 2, 1]
    assert [r["from_version"] for r in decider] == [5, 4, 3, 2, 1]
    assert [r["from_version"] for r in genuine] == [6, 5, 3, 2, 1]
    assert [r["from_version"] for r in track] == [6, 3]
    auto_row = next(r for r in everything if r["from_version"] == 4)
    assert auto_row["critic_auto"] is True
    summ = everything[0]
    assert summ["human_agrees_critic"] is False
    assert summ["human_sections"] == {"approved": ["memory"]}
    assert everything[-1]["human_agrees_critic"] is True
    assert all(len(r["critic_reason"]) <= 1 for r in short)


# ------------------------------------------------- feedback_agent lesson lines


@pytest.fixture
def feedback_module(monkeypatch, review_db):
    config_stub = types.ModuleType("config")
    config_stub.engine = review_db
    config_stub.get_current_config_hash = lambda: CFG
    for name in ("PromptManager", "session", "openai", "get_agent_model", "get_model_token_params",
                 "get_model_temperature_params", "append_reasoning_guidance",
                 "get_agent_reasoning_level", "get_reasoning_token_cap", "get_reasoning_params"):
        setattr(config_stub, name, lambda *_a, **_k: None)
    config_stub.GPT_MODEL = "gpt-test"
    config_stub.MODEL_TEMPERATURE = 0
    monkeypatch.setitem(sys.modules, "config", config_stub)
    monkeypatch.setitem(sys.modules, "yfinance", types.ModuleType("yfinance"))
    monkeypatch.setitem(sys.modules, "pandas", types.ModuleType("pandas"))
    monkeypatch.delitem(sys.modules, "feedback_agent", raising=False)
    module = importlib.import_module("feedback_agent")
    yield module
    sys.modules.pop("feedback_agent", None)


def test_feedback_lessons_include_unclicked_critic_verdicts(feedback_module, review_db):
    for n in range(10, 20):
        _insert(review_db, n, human="approve", agrees=False, reason=f"labeled {n}")
    _insert(review_db, 2, conf=0.8, reason="pending critic objection")
    _insert(review_db, 3, conf=0.0, reason="Critic unavailable")
    tracker = object.__new__(feedback_module.TradeOutcomeTracker)
    lines = tracker._get_prompt_review_lessons().splitlines()
    assert len(lines) == 8                    # 5 labeled + 1 pending genuine + 2 labeled fill
    assert sum("human=pending" in ln for ln in lines) == 1
    assert lines[-1].startswith("- 2026-09-01 DeciderAgent v2: critic=reject(0.8) human=pending")
    assert lines[-1].endswith("pending critic objection")
    assert "OVERRODE critic" in lines[0] and "v19" in lines[0]
    assert not any("Critic unavailable" in ln for ln in lines)


def test_feedback_lessons_fail_safe_to_empty(feedback_module, monkeypatch):
    class _Broken:
        def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(feedback_module, "engine", _Broken())
    tracker = object.__new__(feedback_module.TradeOutcomeTracker)
    assert tracker._get_prompt_review_lessons() == ""


# ------------------------------------------------------ dashboard wrapper wiring


def test_dashboard_review_history_wiring(dashboard_server_module, monkeypatch):
    module, _ = dashboard_server_module
    calls = []

    class _Engine:
        def connect(self):
            return _Conn()

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def _fake_window(conn, config_hash, **kwargs):
        calls.append((config_hash, kwargs))
        return [{"from_version": 1}]

    monkeypatch.setattr(module, "engine", _Engine())
    monkeypatch.setattr(module, "fetch_review_window", _fake_window)

    assert module._fetch_prompt_review_history("h1", "DeciderAgent", limit=8) == [{"from_version": 1}]
    assert calls[-1] == ("h1", {"agent_type": "DeciderAgent", "genuine_only": False, "reason_chars": 300,
                                "limit": 8, "human_quota": 5, "critic_quota": 3})
    module._fetch_critic_track_record("h1")
    assert calls[-1] == ("h1", {"agent_type": None, "genuine_only": True, "reason_chars": 300,
                                "limit": 10, "human_quota": 10, "critic_quota": 0})

    def _boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(module, "fetch_review_window", _boom)
    assert module._fetch_prompt_review_history("h1", "DeciderAgent") == []
