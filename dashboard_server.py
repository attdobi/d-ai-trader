# --- D-AI-Trader bootstrap (auto-inserted) ---
import os as _os, sys as _sys
_repo_root = _os.environ.get("DAI_TRADER_ROOT") or _os.path.dirname(_os.path.abspath(__file__))
_os.environ.setdefault("DAI_TRADER_ROOT", _repo_root)
if _repo_root not in _sys.path:
    _sys.path.insert(0, _repo_root)
_os.environ.setdefault("DAI_DISABLE_UC", "1")
try:
    import sitecustomize  # noqa: F401
except Exception:
    pass
# --- end bootstrap ---

from flask import Flask, render_template, jsonify, request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from config import engine, get_gpt_model, get_prompt_version_config, get_trading_mode, get_current_config_hash, set_gpt_model, SCHWAB_ACCOUNT_HASH
import importlib
import initialize_prompts as default_prompts_module
from prompt_manager import initialize_config_prompts
from decider_agent import (
    extract_companies_from_summaries,
    build_momentum_recap,
    fetch_holdings,
    store_momentum_snapshot,
    SUMMARY_MAX_CHARS,
)

# Apply model from environment if specified
if _os.environ.get("DAI_GPT_MODEL"):
    set_gpt_model(_os.environ["DAI_GPT_MODEL"])
import json
import pandas as pd
import threading
import time
import yfinance as yf
from datetime import datetime, timedelta
from feedback_agent import TradeOutcomeTracker
from schwab_client import schwab_client
import subprocess
import sys
import os

# Configuration
REFRESH_INTERVAL_MINUTES = 10
app = Flask(__name__)

FEEDBACK_DEFAULTS = default_prompts_module.DEFAULT_PROMPTS["FeedbackAgent"]
DEFAULT_FEEDBACK_SYSTEM_PROMPT = FEEDBACK_DEFAULTS["system_prompt"]
DEFAULT_FEEDBACK_USER_PROMPT = FEEDBACK_DEFAULTS["user_prompt_template"]
DEFAULT_FEEDBACK_DESCRIPTION = FEEDBACK_DEFAULTS["description"]

# Initialize trading interface for Schwab integration
try:
    from trading_interface import trading_interface
    SCHWAB_ENABLED = True
except ImportError:
    SCHWAB_ENABLED = False
    print("Warning: Trading interface not available, Schwab features disabled")


def _refresh_holdings_with_quotes(holdings):
    """
    Update live pricing for Schwab holdings using yfinance to keep dashboard values current.
    """
    updated = False
    for row in holdings:
        symbol = row.get("ticker")
        if not symbol or symbol == "CASH":
            continue
        try:
            ticker = yf.Ticker(symbol)
            fast = getattr(ticker, "fast_info", None)
            price = None
            if fast:
                price = fast.get("last_price") or fast.get("regular_market_price") or fast.get("previous_close")
            if price is None:
                info = getattr(ticker, "info", {}) or {}
                price = info.get("regularMarketPrice") or info.get("regularMarketPreviousClose")
            if price:
                price = float(price)
                shares = float(row.get("shares") or 0)
                cost_basis = float(row.get("total_value") or (row.get("purchase_price", 0) * shares))
                row["current_price"] = price
                row["current_value"] = price * shares
                row["gain_loss"] = row["current_value"] - cost_basis
                updated = True
        except Exception as exc:
            print(f"⚠️  Unable to refresh quote for {symbol}: {exc}")
    return updated


def _ensure_v0_prompt(conn, agent_type, config_hash, prompt_payload):
    """Ensure the v0 prompt for the given agent/config matches code defaults."""
    if not prompt_payload:
        return

    system_prompt = prompt_payload.get("system_prompt")
    user_prompt = prompt_payload.get("user_prompt_template") or prompt_payload.get("user_prompt")
    description = prompt_payload.get("description")

    if not system_prompt or not user_prompt:
        return

    delete_params = {
        "agent_type": agent_type,
        "config_hash": config_hash,
    }

    def _delete_rows(table_name, template):
        conn.execute(text(template), delete_params)

    def _insert_row(table_name, insert_sql):
        values = {
            "agent_type": agent_type,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "description": description,
            "config_hash": 'global' if config_hash == "global" else config_hash,
        }
        conn.execute(text(insert_sql), values)

    # Base table
    if config_hash == "global":
        _delete_rows("prompt_versions", """
            DELETE FROM prompt_versions
            WHERE agent_type = :agent_type
              AND version = 0
              AND (config_hash = 'global' OR config_hash IS NULL)
        """)
    else:
        _delete_rows("prompt_versions", """
            DELETE FROM prompt_versions
            WHERE agent_type = :agent_type
              AND version = 0
              AND config_hash = :config_hash
        """)

    _insert_row("prompt_versions", """
        INSERT INTO prompt_versions
            (agent_type, version, system_prompt, user_prompt_template, description, created_by, is_active, config_hash)
        VALUES
            (:agent_type, 0, :system_prompt, :user_prompt, :description, 'prompt_reset', TRUE, :config_hash)
    """)

    def _table_exists(table_name):
        result = conn.execute(text("SELECT to_regclass(:tbl)"), {"tbl": table_name}).scalar()
        return result is not None

    def _table_has_column(table_name, column_name):
        return conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = :table AND column_name = :column
        """), {"table": table_name, "column": column_name}).fetchone() is not None

    if _table_exists('ai_agent_prompts') and _table_has_column('ai_agent_prompts', 'agent_type'):
        has_config = _table_has_column('ai_agent_prompts', 'config_hash')
        use_version = _table_has_column('ai_agent_prompts', 'version')

        if not has_config:
            # Cannot scope by config hash; skip syncing to avoid corrupting shared rows
            return
        else:
            if config_hash == "global":
                if use_version:
                    _delete_rows("ai_agent_prompts", """
                        DELETE FROM ai_agent_prompts
                        WHERE agent_type = :agent_type
                          AND version = 0
                          AND (config_hash = 'global' OR config_hash IS NULL)
                    """)
                else:
                    _delete_rows("ai_agent_prompts", """
                        DELETE FROM ai_agent_prompts
                        WHERE agent_type = :agent_type
                          AND (config_hash = 'global' OR config_hash IS NULL)
                    """)
            else:
                if use_version:
                    _delete_rows("ai_agent_prompts", """
                        DELETE FROM ai_agent_prompts
                        WHERE agent_type = :agent_type
                          AND version = 0
                          AND config_hash = :config_hash
                    """)
                else:
                    _delete_rows("ai_agent_prompts", """
                        DELETE FROM ai_agent_prompts
                        WHERE agent_type = :agent_type
                          AND config_hash = :config_hash
                    """)

        if has_config:
            if use_version:
                _insert_row("ai_agent_prompts", """
                    INSERT INTO ai_agent_prompts
                        (agent_type, version, system_prompt, user_prompt, description, created_by, is_active, config_hash)
                    VALUES
                        (:agent_type, 0, :system_prompt, :user_prompt, :description, 'prompt_reset', TRUE, :config_hash)
                """)
            else:
                _insert_row("ai_agent_prompts", """
                    INSERT INTO ai_agent_prompts
                        (agent_type, system_prompt, user_prompt, description, created_by, is_active, config_hash)
                    VALUES
                        (:agent_type, :system_prompt, :user_prompt, :description, 'prompt_reset', TRUE, :config_hash)
                """)

    if _table_exists('unified_prompts') and _table_has_column('unified_prompts', 'agent_type'):
        if config_hash == "global":
            _delete_rows("unified_prompts", """
                DELETE FROM unified_prompts
                WHERE agent_type = :agent_type
                  AND version = 0
                  AND (config_hash = 'global' OR config_hash IS NULL)
            """)
        else:
            _delete_rows("unified_prompts", """
                DELETE FROM unified_prompts
                WHERE agent_type = :agent_type
                  AND version = 0
                  AND config_hash = :config_hash
            """)

        _insert_row("unified_prompts", """
            INSERT INTO unified_prompts
                (agent_type, version, system_prompt, user_prompt_template, description, created_by, is_active, config_hash)
            VALUES
                (:agent_type, 0, :system_prompt, :user_prompt, :description, 'prompt_reset', TRUE, :config_hash)
        """)


class _SafeFormatDict(dict):
    """Dictionary that leaves unknown keys in braces when formatting."""
    def __missing__(self, key):
        return f"{{{key}}}"

def _normalize_feedback_value(value):
    """Convert stored feedback (JSON/text/None) into a clean display string."""
    if value is None:
        return ""
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return ""
        try:
            parsed = json.loads(trimmed)
            return _normalize_feedback_value(parsed)
        except (json.JSONDecodeError, TypeError):
            return trimmed
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, dict):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)

def _render_prompt_text(template, replacements):
    """Render a prompt template with defensive formatting."""
    if not template:
        return None
    try:
        return template.format_map(_SafeFormatDict(replacements))
    except Exception as exc:
        print(f"Prompt render error: {exc}")
        return template

def _collect_prompt_payload(tracker, agent_candidates, key, replacements=None):
    """Build a structured payload for the active prompt of a given agent."""
    replacements = replacements or {}
    if isinstance(agent_candidates, str):
        agent_candidates = [agent_candidates]

    prompt = None
    for candidate in agent_candidates:
        try:
            prompt = tracker.get_active_prompt(candidate)
        except Exception as exc:
            print(f"Error loading prompt for {candidate}: {exc}")
            prompt = None
        if prompt:
            break

    base_payload = {
        "agent": key,
        "version": None,
        "description": None,
        "system_prompt": None,
        "user_prompt": None,
        "rendered_system_prompt": None,
        "rendered_user_prompt": None,
    }
    if not prompt:
        return base_payload

    base_payload.update({
        "version": prompt.get("version") or prompt.get("prompt_version"),
        "description": prompt.get("description"),
        "system_prompt": prompt.get("system_prompt"),
        "user_prompt": prompt.get("user_prompt"),
    })
    base_payload["rendered_system_prompt"] = _render_prompt_text(base_payload["system_prompt"], replacements)
    base_payload["rendered_user_prompt"] = _render_prompt_text(base_payload["user_prompt"], replacements)
    return base_payload

def _format_currency(amount):
    try:
        return "${:,.2f}".format(float(amount))
    except (TypeError, ValueError):
        return "N/A"

def _format_percentage(value, multiplier=1.0):
    try:
        return "{:.2f}%".format(float(value) * multiplier)
    except (TypeError, ValueError):
        return "N/A"

def _build_prompt_context_samples(latest_feedback=None):
    """Create representative context strings for prompt previews."""
    config_hash = get_current_config_hash()
    holdings_rows = []
    summary_rows = []

    with engine.connect() as conn:
        holdings_rows = conn.execute(text("""
            SELECT ticker, shares, current_price, current_value
            FROM holdings
            WHERE is_active = TRUE AND config_hash = :config_hash
        """), {"config_hash": config_hash}).fetchall()

        summary_rows = conn.execute(text("""
            SELECT agent, data, timestamp
            FROM summaries
            WHERE config_hash = :config_hash
            ORDER BY timestamp DESC
            LIMIT 3
        """), {"config_hash": config_hash}).fetchall()

    available_cash_value = 0.0
    holdings_lines = []
    for row in holdings_rows:
        ticker = row.ticker
        value = row.current_value or 0.0
        if ticker and ticker.upper() == "CASH":
            available_cash_value = value
            continue
        shares = row.shares or 0.0
        price = row.current_price or 0.0
        holdings_lines.append(
            f"{ticker}: {shares:.2f} shares @ {_format_currency(price)} (value {_format_currency(value)})"
        )

    holdings_summary = "\n".join(holdings_lines) if holdings_lines else "No active equity positions."
    available_cash_text = _format_currency(available_cash_value)

    summary_entries = []
    for row in summary_rows:
        entry_data = row.data
        if isinstance(entry_data, str):
            try:
                entry_data = json.loads(entry_data)
            except (json.JSONDecodeError, TypeError):
                entry_data = {}
        summary_payload = entry_data.get("summary") if isinstance(entry_data, dict) else {}
        if not isinstance(summary_payload, dict):
            summary_payload = {}

        headlines = summary_payload.get("headlines")
        insights = summary_payload.get("insights")
        timestamp = row.timestamp.strftime("%Y-%m-%d %H:%M") if isinstance(row.timestamp, datetime) else "recent"

        entry_lines = [f"{row.agent} ({timestamp})"]
        if isinstance(headlines, (list, tuple)):
            entry_lines.extend(f"- {headline}" for headline in headlines)
        if insights:
            entry_lines.append(f"Insights: {insights}")
        summary_entries.append("\n".join(entry_lines))

    summaries_text = "\n\n".join(summary_entries) if summary_entries else "No recent summaries available."

    performance_lines = []
    if latest_feedback:
        success_rate = latest_feedback.get("success_rate")
        if success_rate is not None:
            performance_lines.append(f"Success Rate: {_format_percentage(success_rate, multiplier=100.0)}")
        avg_profit = latest_feedback.get("avg_profit_percentage")
        if avg_profit is not None:
            performance_lines.append(f"Average Profit: {_format_percentage(avg_profit)}")
        trades = latest_feedback.get("total_trades_analyzed")
        if trades is not None:
            performance_lines.append(f"Trades Analyzed: {trades}")

    performance_metrics_text = "\n".join(performance_lines) if performance_lines else "Performance metrics available at runtime."
    context_data_text = f"Current Holdings:\n{holdings_summary}\n\nRecent Summaries:\n{summaries_text}"

    return {
        "CURRENT_HOLDINGS_SNAPSHOT": holdings_summary,
        "holdings": holdings_summary,
        "AVAILABLE_CASH": available_cash_text,
        "available_cash": available_cash_text,
        "LATEST_SUMMARIES": summaries_text,
        "summaries": summaries_text,
        "performance_metrics": performance_metrics_text,
        "context_data": context_data_text,
    }


def _parse_summary_row(row):
    """Normalize a raw summaries table row into structured fields."""
    agent = (row.agent or "unknown").strip()
    data = row.data
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            data = {}

    summary_content = data.get("summary") if isinstance(data, dict) else {}
    if isinstance(summary_content, str):
        try:
            summary_content = json.loads(summary_content)
        except (json.JSONDecodeError, TypeError):
            summary_content = {"headlines": [], "insights": summary_content}

    headlines = summary_content.get("headlines") if isinstance(summary_content, dict) else []
    if not isinstance(headlines, (list, tuple)):
        headlines = []
    headlines = [str(h).strip() for h in headlines if h]
    if len(headlines) > 5:
        headlines = headlines[:5]

    insights = summary_content.get("insights") if isinstance(summary_content, dict) else ""
    if not isinstance(insights, str):
        insights = json.dumps(insights, ensure_ascii=False)
    if len(insights) > SUMMARY_MAX_CHARS:
        insights = insights[:SUMMARY_MAX_CHARS] + "... [truncated]"

    timestamp = row.timestamp.isoformat() if isinstance(row.timestamp, datetime) else None

    return {
        "agent": agent,
        "headlines": headlines,
        "insights": insights,
        "timestamp": timestamp,
    }


def generate_summary_analyzer_report(limit=10, force_refresh=False):
    """Run the company extraction and momentum recap pipeline on recent summaries."""
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        latest_run = conn.execute(text("""
            SELECT run_id
            FROM summaries
            WHERE config_hash = :config_hash
            ORDER BY timestamp DESC
            LIMIT 1
        """), {"config_hash": config_hash}).fetchone()

        if not latest_run or not latest_run.run_id:
            return {
                "success": False,
                "error": "No summarizer runs available for the current configuration."
            }

        run_id = latest_run.run_id
        rows = conn.execute(text("""
            SELECT agent, data, timestamp
            FROM summaries
            WHERE config_hash = :config_hash AND run_id = :run_id
            ORDER BY timestamp ASC
        """), {"config_hash": config_hash, "run_id": run_id}).fetchall()

    if not rows:
        return {
            "success": False,
            "error": "No summaries available for the current configuration."
        }

    parsed_summaries = [_parse_summary_row(row) for row in rows]
    parsed_summaries.reverse()  # Oldest first for readability

    summary_parts = []
    extractor_blocks = []
    for entry in parsed_summaries:
        agent_label = entry["agent"]
        headline_text = ", ".join(entry["headlines"][:3])
        insight_text = entry["insights"]
        summary_parts.append(f"{agent_label}: {headline_text} | {insight_text}")
        extractor_blocks.append(
            "\n".join([
                f"Agent: {agent_label}",
                f"Headlines: {headline_text or 'None'}",
                f"Insights: {insight_text or 'None'}",
            ])
        )

    summaries_preview = "\n".join(summary_parts)
    extraction_payload = "\n\n".join(extractor_blocks) if extractor_blocks else summaries_preview

    company_entities = []
    momentum_data = []
    momentum_summary = ""
    momentum_recap = ""
    analysis_timestamp = datetime.utcnow().isoformat() + "Z"

    snapshot_loaded = False
    snapshot = None
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS momentum_snapshots (
                    id SERIAL PRIMARY KEY,
                    config_hash TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    companies_json JSONB,
                    momentum_data JSONB,
                    momentum_summary TEXT,
                    momentum_recap TEXT
                )
            """))
            conn.execute(text("""
                ALTER TABLE momentum_snapshots
                ADD COLUMN IF NOT EXISTS run_id TEXT
            """))
            snapshot = conn.execute(text("""
                SELECT companies_json, momentum_data, momentum_summary, momentum_recap, generated_at
                FROM momentum_snapshots
                WHERE config_hash = :config_hash AND run_id = :run_id
                ORDER BY generated_at DESC
                LIMIT 1
            """), {"config_hash": config_hash, "run_id": run_id}).fetchone()
    except Exception as snapshot_err:
        print(f"⚠️  Momentum snapshot lookup failed: {snapshot_err}")

    if snapshot and not force_refresh:
        snapshot_loaded = True
        try:
            company_entities = json.loads(snapshot.companies_json) if snapshot.companies_json else []
        except Exception:
            company_entities = []
        try:
            momentum_data = json.loads(snapshot.momentum_data) if snapshot.momentum_data else []
        except Exception:
            momentum_data = []
        momentum_summary = snapshot.momentum_summary or ""
        momentum_recap = snapshot.momentum_recap or ""
        if snapshot.generated_at:
            try:
                analysis_timestamp = snapshot.generated_at.isoformat() + "Z"
            except Exception:
                analysis_timestamp = datetime.utcnow().isoformat() + "Z"
    if not snapshot_loaded:
        company_entities = extract_companies_from_summaries(extraction_payload)
        momentum_data, momentum_summary = build_momentum_recap(company_entities)
        momentum_recap = momentum_summary or "Momentum snapshot unavailable. Run the decider to refresh momentum data."
        try:
            store_momentum_snapshot(config_hash, run_id, company_entities, momentum_data, momentum_summary, momentum_recap)
        except Exception as persist_err:
            print(f"⚠️  Failed to persist momentum snapshot: {persist_err}")

    holdings = fetch_holdings()
    cash_balance = next((float(h.get("current_value", 0)) for h in holdings if h.get("ticker") == "CASH"), 0.0)
    stock_holdings = [h for h in holdings if h.get("ticker") not in (None, "CASH")]

    pl_lines = []
    for holding in stock_holdings:
        try:
            ticker = holding.get("ticker", "UNKNOWN")
            cost = float(holding.get("total_value") or 0)
            current = float(holding.get("current_value") or 0)
            pnl_pct = ((current - cost) / cost * 100) if cost else 0.0
            pl_lines.append(f"- {ticker}: {pnl_pct:+.2f}% vs entry (stop loss -3%, take profit +5%)")
        except Exception:
            continue

    holdings_pl_summary = "\n".join(pl_lines)

    if holdings_pl_summary and "Existing Position P/L" not in (momentum_recap or ""):
        if momentum_recap:
            momentum_recap = f"{momentum_recap}\n\nExisting Position P/L:\n{holdings_pl_summary}"
        else:
            momentum_recap = f"Existing Position P/L:\n{holdings_pl_summary}"
    elif not momentum_recap:
        momentum_recap = "- No momentum data available\n\nExisting Position P/L:\n- No open positions"

    return {
        "success": True,
        "summary_count": len(parsed_summaries),
        "run_id": run_id,
        "summaries": parsed_summaries,
        "summaries_preview": summaries_preview,
        "companies": company_entities,
        "momentum_summary": momentum_summary,
        "momentum_data": momentum_data,
        "momentum_recap": momentum_recap,
        "holdings_pl_summary": holdings_pl_summary,
        "available_cash": cash_balance,
        "analysis_timestamp": analysis_timestamp,
    }


def _sync_holdings_with_database(config_hash, holdings, cash_balance):
    """Replace holdings in the database with the live Schwab snapshot."""
    now = datetime.utcnow()
    print(f"🗃️ Syncing holdings for {config_hash}: positions={len(holdings)} cash={cash_balance:.2f}")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM holdings WHERE config_hash = :config_hash"), {"config_hash": config_hash})

        # Cash row
        conn.execute(text("""
            INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price,
                                  purchase_timestamp, current_price_timestamp, total_value, current_value,
                                  gain_loss, reason, is_active)
            VALUES (:config_hash, 'CASH', 1, :cash, :cash, :ts, :ts, :cash, :cash, 0, 'Schwab cash balance', TRUE)
        """), {
            "config_hash": config_hash,
            "cash": cash_balance,
            "ts": now
        })

        for row in holdings:
            shares = float(row.get("shares") or 0)
            current_price = float(row.get("current_price") or 0)
            current_value = float(row.get("current_value") or (shares * current_price))
            total_value = float(row.get("total_value") or (shares * current_price))
            purchase_price = float(row.get("purchase_price") or 0)

            if purchase_price == 0 and shares > 0:
                purchase_price = total_value / shares if total_value else current_price

            gain_loss = float(row.get("gain_loss") or (current_value - total_value))

            conn.execute(text("""
                INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price,
                                      purchase_timestamp, current_price_timestamp, total_value, current_value,
                                      gain_loss, reason, is_active)
                VALUES (:config_hash, :ticker, :shares, :purchase_price, :current_price,
                        :ts, :ts, :total_value, :current_value, :gain_loss, :reason, TRUE)
            """), {
                "config_hash": config_hash,
                "ticker": row.get("ticker"),
                "shares": shares,
                "purchase_price": purchase_price,
                "current_price": current_price,
                "total_value": total_value,
                "current_value": current_value,
                "gain_loss": gain_loss,
                "reason": row.get("reason", "Schwab synced position"),
                "ts": now
            })


def _record_live_portfolio_snapshot(config_hash, total_portfolio_value, cash_balance,
                                    total_invested, total_profit_loss, holdings):
    """Persist live Schwab portfolio snapshot for charting/history."""
    percentage_gain = (total_profit_loss / total_invested * 100) if total_invested else 0
    holdings_snapshot = json.dumps([
        {"ticker": h.get("ticker"), "current_value": h.get("current_value", 0)}
        for h in holdings
    ])

    with engine.begin() as conn:
        latest = conn.execute(text("""
            SELECT timestamp, total_portfolio_value
            FROM portfolio_history
            WHERE config_hash = :config_hash
            ORDER BY timestamp DESC LIMIT 1
        """), {"config_hash": config_hash}).fetchone()

        if latest:
            last_time = latest.timestamp
            last_value = float(latest.total_portfolio_value)
            if abs(last_value - total_portfolio_value) < 0.01 and (datetime.utcnow() - last_time) < timedelta(minutes=5):
                return

        conn.execute(text("""
            INSERT INTO portfolio_history
            (total_portfolio_value, cash_balance, total_invested,
             total_profit_loss, percentage_gain, holdings_snapshot, config_hash)
            VALUES (:total_portfolio_value, :cash_balance, :total_invested,
                    :total_profit_loss, :percentage_gain, :holdings_snapshot, :config_hash)
        """), {
            "total_portfolio_value": total_portfolio_value,
            "cash_balance": cash_balance,
            "total_invested": total_invested,
            "total_profit_loss": total_profit_loss,
            "percentage_gain": percentage_gain,
            "holdings_snapshot": holdings_snapshot,
            "config_hash": config_hash
        })


def _fetch_latest_momentum_snapshot(config_hash):
    if not config_hash:
        return None
    snapshot = None
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS momentum_snapshots (
                    id SERIAL PRIMARY KEY,
                    config_hash TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    companies_json JSONB,
                    momentum_data JSONB,
                    momentum_summary TEXT,
                    momentum_recap TEXT
                )
            """))
            conn.execute(text("""
                ALTER TABLE momentum_snapshots
                ADD COLUMN IF NOT EXISTS run_id TEXT
            """))
            snapshot = conn.execute(text("""
                SELECT companies_json, momentum_data, momentum_summary, momentum_recap, generated_at, run_id
                FROM momentum_snapshots
                WHERE config_hash = :config_hash
                ORDER BY generated_at DESC
                LIMIT 1
            """), {"config_hash": config_hash}).fetchone()
    except Exception as exc:
        print(f"⚠️  Momentum snapshot lookup failed: {exc}")
        snapshot = None
    return snapshot

def _get_active_prompts_bundle():
    """Fetch active prompt data for all primary agents with current feedback applied."""
    tracker = TradeOutcomeTracker()
    latest_feedback = tracker.get_latest_feedback() or {}
    context_samples = _build_prompt_context_samples(latest_feedback)

    momentum_recap_text = "Momentum recap unavailable."
    snapshot = _fetch_latest_momentum_snapshot(get_current_config_hash())
    if snapshot and snapshot.momentum_recap:
        momentum_recap_text = snapshot.momentum_recap

    context_samples.setdefault("momentum_recap", momentum_recap_text)
    context_samples.setdefault("pnl_summary", momentum_recap_text)

    context_samples.setdefault("momentum_recap", momentum_recap_text)
    context_samples.setdefault("pnl_summary", momentum_recap_text)

    summarizer_feedback_text = _normalize_feedback_value(latest_feedback.get("summarizer_feedback"))
    decider_feedback_text = _normalize_feedback_value(latest_feedback.get("decider_feedback"))

    summarizer_feedback_block = ""
    if summarizer_feedback_text:
        summarizer_feedback_block = f"\nPERFORMANCE FEEDBACK: {summarizer_feedback_text}\n"

    replacements_common = {
        **context_samples,
        "content": context_samples.get("summaries", "<LATEST_NEWS_CONTENT>"),
        "feedback_context": summarizer_feedback_block,
        "decider_feedback": decider_feedback_text or "No recent performance feedback available."
    }

    summarizer_payload = _collect_prompt_payload(
        tracker,
        ["SummarizerAgent", "summarizer"],
        "SummarizerAgent",
        replacements={
            "feedback_context": summarizer_feedback_block,
        }
    )

    decider_payload = _collect_prompt_payload(
        tracker,
        ["DeciderAgent", "decider"],
        "DeciderAgent",
        replacements=dict(replacements_common)
    )

    feedback_payload = _collect_prompt_payload(
        tracker,
        ["FeedbackAgent", "feedback_analyzer", "feedback"],
        "FeedbackAgent",
        replacements=dict(replacements_common)
    )

    if not feedback_payload.get("system_prompt"):
        feedback_payload.update({
            "version": feedback_payload.get("version", 0),
            "description": feedback_payload.get("description") or DEFAULT_FEEDBACK_DESCRIPTION,
            "system_prompt": DEFAULT_FEEDBACK_SYSTEM_PROMPT,
            "user_prompt": DEFAULT_FEEDBACK_USER_PROMPT,
        })
        feedback_payload["rendered_system_prompt"] = _render_prompt_text(DEFAULT_FEEDBACK_SYSTEM_PROMPT, replacements_common)
        feedback_payload["rendered_user_prompt"] = _render_prompt_text(DEFAULT_FEEDBACK_USER_PROMPT, replacements_common)

    return {
        "summarizer": summarizer_payload,
        "decider": decider_payload,
        "feedback": feedback_payload
    }

def create_portfolio_history_table():
    """Create portfolio_history table to track portfolio value over time"""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS portfolio_history (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_portfolio_value FLOAT,
                cash_balance FLOAT,
                total_invested FLOAT,
                total_profit_loss FLOAT,
                percentage_gain FLOAT,
                holdings_snapshot JSONB,
                config_hash VARCHAR(50)
            )
        """))

def record_portfolio_snapshot():
    """Record current portfolio state for historical tracking"""
    config_hash = get_current_config_hash()
    with engine.begin() as conn:
        # Get current holdings
        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price, 
                   total_value, current_value, gain_loss
            FROM holdings
            WHERE is_active = TRUE AND config_hash = :config_hash
        """), {"config_hash": config_hash}).fetchall()
        
        holdings = [dict(row._mapping) for row in result]
        
        # Calculate portfolio metrics
        cash_balance = next((h["current_value"] for h in holdings if h["ticker"] == "CASH"), 0)
        stock_holdings = [h for h in holdings if h["ticker"] != "CASH"]
        
        total_current_value = sum(h["current_value"] for h in stock_holdings)
        total_invested = sum(h["total_value"] for h in stock_holdings)
        total_profit_loss = sum(h["gain_loss"] for h in stock_holdings)
        total_portfolio_value = total_current_value + cash_balance
        
        percentage_gain = (total_profit_loss / total_invested * 100) if total_invested > 0 else 0
        
        # Record snapshot
        conn.execute(text("""
            INSERT INTO portfolio_history 
            (total_portfolio_value, cash_balance, total_invested, 
             total_profit_loss, percentage_gain, holdings_snapshot, config_hash)
            VALUES (:total_portfolio_value, :cash_balance, :total_invested, 
                    :total_profit_loss, :percentage_gain, :holdings_snapshot, :config_hash)
        """), {
            "total_portfolio_value": total_portfolio_value,
            "cash_balance": cash_balance,
            "total_invested": total_invested,
            "total_profit_loss": total_profit_loss,
            "percentage_gain": percentage_gain,
            "holdings_snapshot": json.dumps(holdings),
            "config_hash": config_hash
        })

# Initialize portfolio history table
create_portfolio_history_table()


@app.route("/")
def dashboard():
    # Import and ensure portfolio initialization
    from decider_agent import fetch_holdings
    
    # This will trigger initialization if needed
    holdings_data = fetch_holdings()
    
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price, purchase_timestamp, current_timestamp,
                   total_value, current_value, gain_loss, reason
            FROM holdings
            WHERE is_active = TRUE AND config_hash = :config_hash
            ORDER BY CASE WHEN ticker = 'CASH' THEN 1 ELSE 0 END, ticker
        """), {"config_hash": config_hash}).fetchall()

        holdings = [dict(row._mapping) for row in result]

        # Calculate portfolio metrics (default: local DB holdings)
        cash_balance = next((h["current_value"] for h in holdings if h["ticker"] == "CASH"), 0)
        stock_holdings = [h for h in holdings if h["ticker"] != "CASH"]
        
        total_current_value = sum(h["current_value"] for h in stock_holdings)
        total_invested = sum(h["total_value"] for h in stock_holdings)
        total_profit_loss = sum(h["gain_loss"] for h in stock_holdings)
        total_portfolio_value = total_current_value + cash_balance
        
        # Calculate metrics relative to initial $10,000 investment by default
        initial_investment = 10000.0
        net_gain_loss = total_portfolio_value - initial_investment
        net_percentage_gain = (net_gain_loss / initial_investment * 100) if initial_investment else 0
        
        # Calculate percentage gain on invested amount (excluding cash)
        percentage_gain = (total_profit_loss / total_invested * 100) if total_invested > 0 else 0

        schwab_summary = None
        use_schwab_positions = False

        if (
            os.getenv("DAI_SCHWAB_LIVE_VIEW", "0") in {"1", "true", "True"}
            or get_trading_mode() == "live"
            or getattr(trading_interface, "schwab_enabled", False)
        ):
            try:
                schwab_data = trading_interface.sync_schwab_positions()
                if schwab_data.get("status") == "success":
                    positions = schwab_data.get("positions", []) or []
                    holdings = []
                    for position in positions:
                        shares = float(position.get("shares") or 0)
                        avg_price = float(position.get("average_price") or 0)
                        current_price = float(position.get("current_price") or 0)
                        total_cost = float(position.get("total_value") or (shares * avg_price))
                        market_value = float(position.get("market_value") or (shares * current_price))
                        gain_loss = float(position.get("gain_loss") or (market_value - total_cost))

                        holdings.append({
                            "ticker": position.get("symbol", "-").upper(),
                            "shares": shares,
                            "purchase_price": avg_price,
                            "current_price": current_price,
                            "total_value": total_cost,
                            "current_value": market_value,
                            "gain_loss": gain_loss,
                            "reason": "📡 Synced from Schwab"
                        })

                    available_cash = float(
                        schwab_data.get("funds_available_effective")
                        or schwab_data.get("funds_available_for_trading")
                        or schwab_data.get("cash_balance")
                        or 0.0
                    )
                    raw_cash_balance = float(
                        schwab_data.get("cash_balance_settled")
                        or schwab_data.get("cash_balance")
                        or 0.0
                    )
                    unsettled_cash = float(schwab_data.get("unsettled_cash") or 0.0)
                    funds_components = schwab_data.get("funds_available_components", {})
                    ledger_comp = schwab_data.get("ledger_components", {})

                    total_invested = sum(row["total_value"] for row in holdings)
                    total_current_value = sum(row["current_value"] for row in holdings)
                    total_profit_loss = sum(row["gain_loss"] for row in holdings)
                    total_portfolio_value = total_current_value + available_cash
                    cash_balance = available_cash

                    # Use account valuation relative to baseline (first snapshot) for net gain/loss
                    if not baseline_snapshot:
                        initial_investment = total_portfolio_value
                        baseline_snapshot = type("Baseline", (), {
                            "total_portfolio_value": total_portfolio_value,
                            "cash_balance": cash_balance,
                            "total_invested": total_invested,
                            "total_profit_loss": total_profit_loss,
                            "percentage_gain": 0.0,
                        })()
                    net_gain_loss = total_portfolio_value - float(baseline_snapshot.total_portfolio_value or initial_investment)
                    net_percentage_gain = (
                        (net_gain_loss / float(baseline_snapshot.total_portfolio_value)) * 100
                        if baseline_snapshot and float(baseline_snapshot.total_portfolio_value)
                        else 0
                    )
                    percentage_gain = (
                        (total_profit_loss / total_invested * 100)
                        if total_invested
                        else 0
                    )

                    account_info = schwab_data.get("account_info", {})
                    schwab_summary = {
                        "account_hash": account_info.get("account_hash") or SCHWAB_ACCOUNT_HASH,
                        "account_number": account_info.get("account_number"),
                        "account_type": account_info.get("account_type"),
                        "readonly": schwab_data.get("readonly_mode", False),
                        "last_updated": schwab_data.get("last_updated"),
                        "cash_balance": raw_cash_balance,
                        "funds_available_for_trading": available_cash,
                        "unsettled_cash": unsettled_cash,
                        "order_reserve": schwab_data.get("order_reserve", 0.0),
                        "funds_available_explicit": account_info.get("funds_available_explicit"),
                        "funds_available_derived": account_info.get("funds_available_derived"),
                        "same_day_net_activity": account_info.get("same_day_net_activity"),
                        "buying_power": account_info.get("buying_power"),
                        "day_trading_buying_power": account_info.get("day_trading_buying_power"),
                        "funds_available_components": funds_components,
                        "ledger_components": ledger_comp,
                        "open_orders_count": schwab_data.get("open_orders_count", 0),
                    }
                    use_schwab_positions = True

                    # Persist live snapshot for dashboards/charts
                    _sync_holdings_with_database(config_hash, holdings, available_cash)
                    _record_live_portfolio_snapshot(
                        config_hash,
                        total_portfolio_value,
                        available_cash,
                        total_invested,
                        total_profit_loss,
                        holdings,
                    )
                else:
                    warning = schwab_data.get("message") or schwab_data.get("error")
                    if warning:
                        print(f"⚠️ Schwab sync unavailable: {warning}")
            except Exception as schwab_error:
                print(f"Error syncing Schwab data for dashboard: {schwab_error}")

        # Get current system configuration with prompt versions
        try:
            tracker = TradeOutcomeTracker()
            summarizer_prompt = tracker.get_active_prompt('SummarizerAgent')
            decider_prompt = tracker.get_active_prompt('DeciderAgent')
            
            prompt_versions = {
                'summarizer_version': summarizer_prompt['version'] if summarizer_prompt else 0,
                'decider_version': decider_prompt['version'] if decider_prompt else 0
            }
        except Exception as e:
            print(f"Error getting prompt versions: {e}")
            prompt_versions = {'summarizer_version': 0, 'decider_version': 0}
        
        current_config = {
            'gpt_model': get_gpt_model(),
            'prompt_config': get_prompt_version_config(),
            'trading_mode': get_trading_mode(),
            'config_hash': get_current_config_hash(),
            'prompt_versions': prompt_versions
        }

        baseline_snapshot = conn.execute(text("""
            SELECT total_portfolio_value, cash_balance, total_invested,
                   total_profit_loss, percentage_gain
            FROM portfolio_history
            WHERE config_hash = :config_hash
            ORDER BY timestamp ASC
            LIMIT 1
        """), {"config_hash": config_hash}).fetchone()

        if baseline_snapshot:
            baseline_total_value = float(baseline_snapshot.total_portfolio_value or 0.0)
            baseline_cash = float(baseline_snapshot.cash_balance or 0.0)
            baseline_invested = float(baseline_snapshot.total_invested or 0.0)
            baseline_profit_loss = float(baseline_snapshot.total_profit_loss or 0.0)
            baseline_percentage = float(baseline_snapshot.percentage_gain or 0.0)

            if baseline_total_value or baseline_invested:
                total_profit_loss = baseline_profit_loss
                percentage_gain = baseline_percentage
                initial_investment = baseline_invested if baseline_invested > 0 else baseline_total_value
                if initial_investment == 0:
                    initial_investment = 10000.0
                net_gain_loss = baseline_profit_loss
                net_percentage_gain = baseline_percentage
                total_portfolio_value = baseline_total_value
                cash_balance = baseline_cash
                total_invested = baseline_invested
                total_current_value = max(0.0, total_portfolio_value - cash_balance)

        return render_template("dashboard.html", active_tab="dashboard", holdings=holdings,
                               total_value=total_portfolio_value, cash_balance=cash_balance,
                               portfolio_value=total_current_value, total_invested=total_invested,
                               total_profit_loss=total_profit_loss, percentage_gain=percentage_gain,
                               initial_investment=initial_investment, net_gain_loss=net_gain_loss,
                               net_percentage_gain=net_percentage_gain, current_config=current_config,
                               schwab_summary=schwab_summary,
                               use_schwab_positions=use_schwab_positions)

@app.template_filter('from_json')
def from_json_filter(s):
    try:
        return json.loads(s)
    except Exception:
        return {}


@app.route("/trades")
def trade_decisions():
    import pytz
    config_hash = get_current_config_hash()
    pacific_tz = pytz.timezone('US/Pacific')
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM trade_decisions 
            WHERE config_hash = :config_hash
              AND data::text NOT LIKE '%%Max retries reached%%'
              AND data::text NOT LIKE '%%API error, no response%%'
            ORDER BY id DESC LIMIT 20
        """), {"config_hash": config_hash}).fetchall()
        
        trades = []
        for row in result:
            trade_dict = dict(row._mapping)
            
            # Format timestamp in Pacific time
            timestamp = trade_dict.get('timestamp')
            if timestamp:
                if timestamp.tzinfo is None:
                    timestamp = pacific_tz.localize(timestamp)
                else:
                    timestamp = timestamp.astimezone(pacific_tz)
                # Format with correct timezone abbreviation (PDT or PST)
                tz_abbr = timestamp.strftime("%Z")
                trade_dict['timestamp'] = timestamp.strftime(f"%m/%d/%Y, %I:%M:%S %p {tz_abbr}")
            
            # Parse JSON if data is a string
            if isinstance(trade_dict['data'], str):
                try:
                    parsed_data = json.loads(trade_dict['data'])
                    trade_dict['data'] = parsed_data
                except json.JSONDecodeError:
                    # If JSON parsing fails, create empty list
                    trade_dict['data'] = []
            
            # Ensure data is a list and each item is a dict
            if not isinstance(trade_dict['data'], list):
                trade_dict['data'] = []
            else:
                # Clean up each decision to ensure it's a dict with proper fields
                # IMPORTANT: Preserve ALL fields including shares, total_value for display
                cleaned_data = []
                for decision in trade_dict['data']:
                    if isinstance(decision, dict):
                        # Preserve all fields from database (including shares, total_value)
                        cleaned_decision = {
                            'ticker': decision.get('ticker', 'N/A'),
                            'action': decision.get('action', 'N/A'),
                            'amount_usd': decision.get('amount_usd', 0),
                            'shares': decision.get('shares'),  # ← ADDED
                            'total_value': decision.get('total_value'),  # ← ADDED
                            'reason': decision.get('reason', 'N/A'),
                            'execution_status': decision.get('execution_status')  # For market closed flag
                        }
                        cleaned_data.append(cleaned_decision)
                    elif isinstance(decision, str):
                        # If decision is a string, try to parse it
                        try:
                            parsed_decision = json.loads(decision)
                            if isinstance(parsed_decision, dict):
                                cleaned_decision = {
                                    'ticker': parsed_decision.get('ticker', 'N/A'),
                                    'action': parsed_decision.get('action', 'N/A'),
                                    'amount_usd': parsed_decision.get('amount_usd', 0),
                                    'shares': parsed_decision.get('shares'),  # ← ADDED
                                    'total_value': parsed_decision.get('total_value'),  # ← ADDED
                                    'reason': parsed_decision.get('reason', 'N/A')
                                }
                                cleaned_data.append(cleaned_decision)
                        except:
                            # If parsing fails, skip this decision
                            continue
                
                trade_dict['data'] = cleaned_data
            
            trades.append(trade_dict)
        
        return render_template("trades.html", active_tab="trades", trades=trades)

@app.route("/summaries")
def summaries():
    import pytz
    config_hash = get_current_config_hash()
    pacific_tz = pytz.timezone('US/Pacific')
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM summaries 
            WHERE config_hash = :config_hash
              AND data::text NOT LIKE '%%API error, no response%%'
            ORDER BY id DESC LIMIT 20
        """), {"config_hash": config_hash}).fetchall()

        summaries = []
        for row in result:
            try:
                # Parse the outer JSON structure
                outer = json.loads(row.data)
                summary_data = outer.get("summary", {})
                
                # Handle case where summary_data might be a string or dict
                if isinstance(summary_data, str):
                    try:
                        summary_data = json.loads(summary_data)
                    except json.JSONDecodeError:
                        # If it's not JSON, treat it as plain text
                        summary_data = {"headlines": [], "insights": summary_data}
                elif not isinstance(summary_data, dict):
                    summary_data = {"headlines": [], "insights": str(summary_data)}

                # Format timestamp in Pacific time
                timestamp = row.timestamp
                if timestamp:
                    # If timestamp is naive, assume it's Pacific time
                    if timestamp.tzinfo is None:
                        timestamp = pacific_tz.localize(timestamp)
                    else:
                        # Convert to Pacific time if it's in another timezone
                        timestamp = timestamp.astimezone(pacific_tz)
                    # Format as readable Pacific time (PDT or PST depending on season)
                    tz_abbr = timestamp.strftime("%Z")  # Gets PDT or PST automatically
                    formatted_timestamp = timestamp.strftime(f"%m/%d/%Y, %I:%M:%S %p {tz_abbr}")
                else:
                    formatted_timestamp = "Unknown"

                summaries.append({
                    "agent": row.agent,
                    "timestamp": formatted_timestamp,
                    "headlines": summary_data.get("headlines", []),
                    "insights": summary_data.get("insights", "")
                })
            except Exception as e:
                print(f"Failed to parse summary row {row.id}: {e}")
                print(f"Raw data: {row.data[:200]}...")
                continue

        return render_template("summaries.html", summaries=summaries)

@app.route("/api/configuration")
def api_configuration():
    """Get current system configuration"""
    try:
        # Get current prompt versions
        try:
            from prompt_manager import get_active_prompt_emergency_patch
            summarizer_prompt = get_active_prompt_emergency_patch('SummarizerAgent')
            decider_prompt = get_active_prompt_emergency_patch('DeciderAgent')
            
            prompt_versions = {
                'summarizer_version': summarizer_prompt['version'] if summarizer_prompt else 0,
                'decider_version': decider_prompt['version'] if decider_prompt else 0
            }
        except Exception as e:
            print(f"Error getting unified prompt versions: {e}")
            prompt_versions = {'summarizer_version': 0, 'decider_version': 0}
        
        current_config = {
            'gpt_model': get_gpt_model(),
            'prompt_config': get_prompt_version_config(),
            'trading_mode': get_trading_mode(),
            'config_hash': get_current_config_hash(),
            'prompt_versions': prompt_versions
        }
        return jsonify(current_config)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route("/api/holdings")
def api_holdings():
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT * FROM holdings WHERE is_active = TRUE AND config_hash = :config_hash
        """), {"config_hash": config_hash}).fetchall()
        return jsonify([dict(row._mapping) for row in result])

@app.route("/api/history")
def api_history():
    ticker = request.args.get("ticker")
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        if ticker:
            result = conn.execute(text("""
                SELECT current_price_timestamp, current_value FROM holdings
                WHERE ticker = :ticker AND config_hash = :config_hash 
                ORDER BY current_price_timestamp ASC
            """), {"ticker": ticker, "config_hash": config_hash}).fetchall()
        else:
            result = conn.execute(text("""
                SELECT current_timestamp, SUM(current_value) AS total_value
                FROM holdings
                WHERE config_hash = :config_hash
                GROUP BY current_timestamp ORDER BY current_timestamp ASC
            """), {"config_hash": config_hash}).fetchall()

        return jsonify([dict(row._mapping) for row in result])

@app.route("/api/portfolio-history")
def api_portfolio_history():
    """Get portfolio performance over time - strictly filtered by current config"""
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT timestamp, total_portfolio_value, total_invested, 
                   total_profit_loss, percentage_gain, cash_balance
            FROM portfolio_history 
            WHERE config_hash = :config_hash
            ORDER BY timestamp ASC
        """), {"config_hash": config_hash}).fetchall()

    payload = []
    for row in result:
        record = dict(row._mapping)
        ts = record.get("timestamp")
        if isinstance(ts, datetime):
            record["timestamp"] = ts.isoformat()
        payload.append(record)

    return jsonify(payload)

@app.route("/api/portfolio-performance")
def api_portfolio_performance():
    """Get portfolio performance relative to initial $10,000 investment - strictly filtered by current config"""
    config_hash = get_current_config_hash()

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT timestamp, total_portfolio_value, cash_balance,
                   total_invested, total_profit_loss
            FROM portfolio_history 
            WHERE config_hash = :config_hash
            ORDER BY timestamp ASC
        """), {"config_hash": config_hash}).fetchall()

    rows = [dict(row._mapping) for row in result]
    if not rows:
        return jsonify([])

    base = rows[0]["total_portfolio_value"] or 0
    output = []
    for row in rows:
        total_value = float(row.get("total_portfolio_value") or 0)
        net_gain_loss = total_value - base
        net_percentage = (net_gain_loss / base * 100) if base else 0
        output.append({
            "timestamp": row.get("timestamp").isoformat() if isinstance(row.get("timestamp"), datetime) else row.get("timestamp"),
            "total_portfolio_value": total_value,
            "cash_balance": float(row.get("cash_balance") or 0),
            "net_gain_loss": net_gain_loss,
            "net_percentage_gain": net_percentage,
        })

    return jsonify(output)


@app.route("/api/prompts/reset", methods=["POST"])
def api_reset_prompts_to_baseline():
    """Reset prompt blueprints to their v0 baseline for the active configuration."""
    config_hash = get_current_config_hash()
    agents = ["SummarizerAgent", "DeciderAgent", "FeedbackAgent"]
    try:
        importlib.reload(default_prompts_module)
        latest_defaults = default_prompts_module.DEFAULT_PROMPTS

        # Sync global baselines first so initialize_config_prompts copies fresh text
        with engine.begin() as conn:
            for agent, payload in latest_defaults.items():
                _ensure_v0_prompt(conn, agent, "global", payload)

        initialize_config_prompts(config_hash)
        with engine.begin() as conn:
            for agent, payload in latest_defaults.items():
                _ensure_v0_prompt(conn, agent, config_hash, payload)

        with engine.begin() as conn:
            for agent in agents:
                conn.execute(text(
                    "UPDATE prompt_versions SET is_active = FALSE WHERE agent_type = :agent AND config_hash = :cfg"
                ), {"agent": agent, "cfg": config_hash})

                updated = conn.execute(text(
                    """
                    UPDATE prompt_versions
                    SET is_active = TRUE
                    WHERE agent_type = :agent AND config_hash = :cfg AND version = 0
                    """
                ), {"agent": agent, "cfg": config_hash})

                if updated.rowcount == 0:
                    conn.execute(text(
                        """
                        UPDATE prompt_versions
                        SET is_active = TRUE
                        WHERE agent_type = :agent AND version = 0 AND (config_hash IS NULL OR config_hash = 'global')
                        """
                    ), {"agent": agent})

        return jsonify({"status": "success"})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

@app.route("/api/profit-loss")
def api_profit_loss():
    """Get current profit/loss breakdown by holding"""
    config_hash = get_current_config_hash()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT ticker, shares, purchase_price, current_price,
                   total_value, current_value, gain_loss,
                   CASE 
                       WHEN total_value > 0 THEN (gain_loss / total_value * 100)
                       ELSE 0 
                   END as percentage_gain
            FROM holdings
            WHERE is_active = TRUE AND ticker != 'CASH' AND config_hash = :config_hash
            ORDER BY gain_loss DESC
        """), {"config_hash": config_hash}).fetchall()
        
        return jsonify([dict(row._mapping) for row in result])

@app.route('/api/feedback')
def get_feedback_data():
    """Get feedback analysis data"""
    try:
        tracker = TradeOutcomeTracker()
        
        # Get recent feedback (gracefully handle missing AI key)
        try:
            latest_feedback = tracker.get_latest_feedback()
        except Exception:
            latest_feedback = None
        
        # Get trade outcomes for different periods
        periods = [7, 14, 30]
        period_data = {}
        
        for days in periods:
            # Compute metrics without AI call to avoid API failures impacting the dashboard
            metrics = tracker.compute_recent_outcomes_metrics(days_back=days)
            period_data[f'{days}d'] = {
                'total_trades': metrics['total_trades'],
                'success_rate': metrics['success_rate'],
                'avg_profit': metrics['avg_profit']
            }
        
        return jsonify({
            'latest_feedback': latest_feedback,
            'period_analysis': period_data,
            'status': 'success'
        })
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'error'})

@app.route('/api/trade_outcomes')
def get_trade_outcomes():
    """Get recent trade outcomes"""
    try:
        config_hash = get_current_config_hash()
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT ticker, sell_timestamp, purchase_price, sell_price, 
                       shares, gain_loss_amount, gain_loss_percentage, 
                       outcome_category, hold_duration_days
                FROM trade_outcomes 
                WHERE config_hash = :config_hash
                ORDER BY sell_timestamp DESC 
                LIMIT 50
            """), {"config_hash": config_hash}).fetchall()
            
            outcomes = []
            for row in result:
                outcomes.append({
                    'ticker': row.ticker,
                    'sell_date': row.sell_timestamp.isoformat() if row.sell_timestamp else None,
                    'purchase_price': float(row.purchase_price),
                    'sell_price': float(row.sell_price),
                    'shares': float(row.shares),
                    'net_gain_dollars': float(row.gain_loss_amount),
                    'gain_loss_pct': float(row.gain_loss_percentage),
                    'category': row.outcome_category,
                    'hold_days': row.hold_duration_days
                })
            
            return jsonify(outcomes)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/feedback_log')
def get_feedback_log():
    """Get feedback log with timestamps"""
    try:
        with engine.connect() as conn:
            # Get agent feedback entries
            config_hash = get_current_config_hash()
            feedback_result = conn.execute(text("""
                SELECT analysis_timestamp, lookback_period_days, total_trades_analyzed,
                       success_rate, avg_profit_percentage, summarizer_feedback, decider_feedback
                FROM agent_feedback 
                WHERE config_hash = :config_hash
                ORDER BY analysis_timestamp DESC 
                LIMIT 100
            """), {"config_hash": config_hash}).fetchall()
            
            # Get instruction updates
            instruction_result = conn.execute(text("""
                SELECT agent_type, update_timestamp, reason_for_update, performance_trigger
                FROM agent_instruction_updates 
                WHERE config_hash = :config_hash
                ORDER BY update_timestamp DESC 
                LIMIT 50
            """), {"config_hash": config_hash}).fetchall()
            
            feedback_log = []
            for row in feedback_result:
                feedback_log.append({
                    'type': 'feedback_analysis',
                    'timestamp': row.analysis_timestamp.isoformat() if row.analysis_timestamp else None,
                    'lookback_days': row.lookback_period_days,
                    'trades_analyzed': row.total_trades_analyzed,
                    'success_rate': float(row.success_rate) * 100,
                    'avg_profit': float(row.avg_profit_percentage) * 100,
                    'summarizer_feedback': row.summarizer_feedback,
                    'decider_feedback': row.decider_feedback
                })
            
            for row in instruction_result:
                feedback_log.append({
                    'type': 'instruction_update',
                    'timestamp': row.update_timestamp.isoformat() if row.update_timestamp else None,
                    'agent_type': row.agent_type,
                    'reason': row.reason_for_update,
                    'performance_trigger': row.performance_trigger
                })
            
            # Sort by timestamp descending
            feedback_log.sort(key=lambda x: x['timestamp'], reverse=True)
            
            return jsonify(feedback_log)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/generate_ai_feedback', methods=['POST'])
def generate_ai_feedback():
    """Generate AI feedback for a specific agent"""
    try:
        data = request.get_json()
        agent_type = data.get('agent_type')
        context_data = data.get('context_data')
        performance_metrics = data.get('performance_metrics')
        is_manual_request = data.get('is_manual_request', True)
        
        if not agent_type:
            return jsonify({'error': 'agent_type is required'}), 400
        
        # Initialize feedback tracker
        from feedback_agent import TradeOutcomeTracker
        feedback_tracker = TradeOutcomeTracker()
        
        # Generate AI feedback
        result = feedback_tracker.generate_ai_feedback_response(
            agent_type=agent_type,
            context_data=context_data,
            performance_metrics=performance_metrics,
            is_manual_request=is_manual_request
        )
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ai_feedback_responses')
def get_ai_feedback_responses():
    """Get recent AI feedback responses"""
    try:
        from feedback_agent import TradeOutcomeTracker
        feedback_tracker = TradeOutcomeTracker()
        
        limit = request.args.get('limit', 50, type=int)
        responses = feedback_tracker.get_recent_ai_feedback_responses(limit=limit)
        
        return jsonify(responses)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/prompts/<agent_type>')
def get_prompts(agent_type):
    """Get prompt history for an agent type using UNIFIED approach"""
    try:
        from prompt_manager import get_active_prompt_emergency_patch
        from config import get_current_config_hash
        
        config_hash = get_current_config_hash()
        
        # Get current active prompt using emergency patch
        try:
            current_prompt = get_active_prompt_emergency_patch(agent_type)
            if current_prompt:
                # Format as expected by frontend
                prompts = [{
                    "id": 1,
                    "prompt_version": current_prompt["version"],
                    "timestamp": "2025-01-01T00:00:00",  # Placeholder timestamp
                    "user_prompt": current_prompt["user_prompt_template"],
                    "system_prompt": current_prompt["system_prompt"],
                    "description": f"Current active prompt v{current_prompt['version']} for config {config_hash[:8]}",
                    "is_active": True,
                    "created_by": "emergency_patch"
                }]
                return jsonify(prompts)
        except Exception as e:
            print(f"Emergency patch failed: {e}")
        
        # Fallback to original method
        from feedback_agent import TradeOutcomeTracker
        feedback_tracker = TradeOutcomeTracker()
        
        limit = request.args.get('limit', 10, type=int)
        prompts = feedback_tracker.get_prompt_history(agent_type, limit=limit)
        
        return jsonify(prompts)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/prompts/<agent_type>/active')
def get_active_prompt(agent_type):
    """Get the currently active prompt for an agent type using UNIFIED approach"""
    try:
        from prompt_manager import get_active_prompt_emergency_patch
        
        prompt = get_active_prompt_emergency_patch(agent_type)
        
        if prompt:
            # Format as expected by frontend
            formatted_prompt = {
                "user_prompt": prompt["user_prompt_template"],
                "system_prompt": prompt["system_prompt"],
                "prompt_version": prompt["version"],
                "version": prompt["version"],
                "description": f"Active prompt v{prompt['version']}"
            }
            return jsonify(formatted_prompt)
        else:
            return jsonify({'error': 'No active prompt found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/prompts/<agent_type>', methods=['POST'])
def save_prompt(agent_type):
    """Save a new prompt version for an agent type"""
    try:
        from feedback_agent import TradeOutcomeTracker
        feedback_tracker = TradeOutcomeTracker()
        
        data = request.get_json()
        user_prompt = data.get('user_prompt')
        system_prompt = data.get('system_prompt')
        description = data.get('description', '')
        created_by = data.get('created_by', 'system')
        
        if not user_prompt or not system_prompt:
            return jsonify({'error': 'user_prompt and system_prompt are required'}), 400
        
        version = feedback_tracker.save_prompt_version(
            agent_type=agent_type,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            description=description,
            created_by=created_by
        )
        
        return jsonify({
            'success': True,
            'version': version,
            'message': f'Prompt version {version} saved successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/feedback')
def feedback_dashboard():
    """Feedback analysis dashboard page"""
    prompts = _get_active_prompts_bundle()
    return render_template('feedback_dashboard.html', prompts=prompts)

@app.route('/api/prompts/active')
def get_active_prompts():
    """Return the active prompt templates for key agents"""
    prompts = _get_active_prompts_bundle()
    return jsonify({
        "status": "success",
        "prompts": prompts
    })


@app.route('/api/run-summary-analyzer', methods=['POST'])
def run_summary_analyzer_endpoint():
    """Ad-hoc trigger for the summary analyzer plus momentum recap."""
    try:
        result = generate_summary_analyzer_report(force_refresh=True)
    except Exception as exc:
        print(f"Summary analyzer error: {exc}")
        result = {"success": False, "error": str(exc)}
        return jsonify(result), 500

    status_code = 200 if result.get('success') else 404
    return jsonify(result), status_code

# Manual trigger endpoints for testing
@app.route('/api/trigger/summarizer', methods=['POST'])
def trigger_summarizer():
    """Manually trigger summarizer agents"""
    try:
        # Import the orchestrator to run summarizer
        from d_ai_trader import DAITraderOrchestrator
        orchestrator = DAITraderOrchestrator()
        
        # Run summarizer in a separate thread to avoid blocking
        def run_summarizer():
            try:
                orchestrator.run_summarizer_agents()
            except Exception as e:
                print(f"Error in manual summarizer run: {e}")
            finally:
                # Clean up resources
                import gc
                gc.collect()
        
        thread = threading.Thread(target=run_summarizer, daemon=True, name="ManualSummarizer")
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Summarizer agents triggered successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/trigger/decider', methods=['POST'])
def trigger_decider():
    """Manually trigger decider agent"""
    try:
        # Import the orchestrator to run decider
        from d_ai_trader import DAITraderOrchestrator
        orchestrator = DAITraderOrchestrator()
        
        # Run decider in a separate thread to avoid blocking
        def run_decider():
            try:
                orchestrator.run_decider_agent()
            except Exception as e:
                print(f"Error in manual decider run: {e}")
            finally:
                # Clean up resources
                import gc
                gc.collect()
        
        thread = threading.Thread(target=run_decider, daemon=True, name="ManualDecider")
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Decider agent triggered successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/trigger/feedback', methods=['POST'])
def trigger_feedback():
    """Manually trigger feedback agent"""
    try:
        # Import the orchestrator to run feedback
        from d_ai_trader import DAITraderOrchestrator
        orchestrator = DAITraderOrchestrator()
        
        # Run feedback in a separate thread to avoid blocking
        def run_feedback():
            try:
                orchestrator.run_feedback_agent()
            except Exception as e:
                print(f"Error in manual feedback run: {e}")
            finally:
                # Clean up resources
                import gc
                gc.collect()
        
        thread = threading.Thread(target=run_feedback, daemon=True, name="ManualFeedback")
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Feedback agent triggered successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/trigger/price-update', methods=['POST'])
def trigger_price_update():
    """Manually trigger price updates for all holdings"""
    def run_price_update():
        try:
            print("=== Manual Price Update Triggered ===")
            config_hash = get_current_config_hash()
            with engine.begin() as conn:
                result = conn.execute(text("SELECT ticker FROM holdings WHERE is_active = TRUE AND ticker != 'CASH' AND config_hash = :config_hash"), {"config_hash": config_hash})
                tickers = [row.ticker for row in result]
                
                updated_count = 0
                for ticker in tickers:
                    try:
                        price = get_current_price_robust(ticker)
                        if price is None:
                            print(f"⚠️  Could not get price for {ticker}")
                            continue

                        now = datetime.utcnow()
                        conn.execute(text("""
                            UPDATE holdings
                            SET current_price = :price,
                                current_value = shares * :price,
                                gain_loss = (shares * :price) - total_value,
                                current_price_timestamp = :current_price_timestamp
                            WHERE ticker = :ticker AND config_hash = :config_hash"""), {
                                "price": price,
                                "current_price_timestamp": now,
                                "ticker": ticker,
                                "config_hash": config_hash
                            })
                        print(f"✅ Updated {ticker}: ${price:.2f}")
                        updated_count += 1
                    except Exception as e:
                        print(f"❌ Failed to update {ticker}: {e}")
                
                # Record portfolio snapshot after updates
                try:
                    record_portfolio_snapshot()
                    print("📊 Portfolio snapshot recorded")
                except Exception as e:
                    print(f"❌ Failed to record portfolio snapshot: {e}")
                
                print(f"🎯 Manual price update completed: {updated_count} holdings updated")
        except Exception as e:
            print(f"Error in manual price update: {e}")
    
    thread = threading.Thread(target=run_price_update, daemon=True)
    thread.start()
    return jsonify({
        'success': True,
        'message': 'Manual price update triggered successfully'
    })

@app.route('/api/trigger/<agent_type>', methods=['POST'])
def trigger_agent(agent_type):
    """Generic route to trigger different agent types"""
    if agent_type == 'all':
        return trigger_all()
    elif agent_type == 'summarizer':
        return trigger_summarizer()
    elif agent_type == 'decider':
        return trigger_decider()
    elif agent_type == 'feedback':
        return trigger_feedback()
    else:
        return jsonify({'error': f'Unknown agent type: {agent_type}'}), 400

@app.route('/api/trigger/all', methods=['POST'])
def trigger_all():
    """Manually trigger all agents in sequence"""
    try:
        # Import the orchestrator to run all agents
        from d_ai_trader import DAITraderOrchestrator
        from config import get_current_config_hash
        import json
        from datetime import datetime
        
        # Ensure config hash is set before running
        config_hash = get_current_config_hash()
        print(f"🔧 Running all agents for config: {config_hash}")
        
        orchestrator = DAITraderOrchestrator()
        
        # Run all agents in sequence in a separate thread
        def run_all():
            try:
                # Use the SAME config hash that's displayed on the website
                # This was set when the .sh script started and should never change
                thread_config_hash = config_hash  # Use the hash from the outer scope
                
                # Ensure config hash is available in this thread
                import os
                os.environ['CURRENT_CONFIG_HASH'] = thread_config_hash
                
                print("🚀 Starting manual run of all agents...")
                print(f"🔧 Config hash in thread: {thread_config_hash} (from website display)")
                
                # 1. Run summarizer
                print("📰 Step 1/3: Running summarizer agents...")
                orchestrator.run_summarizer_agents()
                print("✅ Summarizer completed")
                
                # Small delay to ensure summarizer data is committed
                import time
                time.sleep(2)
                
                # 2. Run decider
                print("🤖 Step 2/3: Running decider agent...")
                orchestrator.run_decider_agent()
                print("✅ Decider completed")
                
                # 3. Run feedback
                print("📊 Step 3/3: Running feedback agent...")
                orchestrator.run_feedback_agent()
                print("✅ Feedback completed")
                
                print("🎉 All agents completed successfully!")
                
            except Exception as e:
                print(f"❌ Error in manual all agents run: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                
                # Store the error in the database so we can see it
                try:
                    with engine.begin() as conn:
                        conn.execute(text("""
                            INSERT INTO system_runs (run_type, status, details)
                            VALUES ('run_all_agents', 'failed', :details)
                        """), {
                            "details": json.dumps({
                                "error": str(e),
                                "config_hash": thread_config_hash,
                                "timestamp": datetime.now().isoformat()
                            })
                        })
                except:
                    pass  # Don't let error logging cause more errors
            finally:
                # Clean up resources to prevent semaphore leaks
                import gc
                gc.collect()
        
        thread = threading.Thread(target=run_all, daemon=True, name="ManualAllAgents")
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'All agents triggered successfully (running in background)'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/run-status')
def get_run_status():
    """Get status of recent runs to debug issues"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT run_type, start_time, end_time, status, 
                       details->>'error' as error,
                       details->>'config_hash' as config_hash
                FROM system_runs 
                WHERE start_time > CURRENT_TIMESTAMP - INTERVAL '1 hour'
                ORDER BY start_time DESC
                LIMIT 10
            """))
            
            runs = []
            for row in result:
                runs.append({
                    'run_type': row.run_type,
                    'start_time': row.start_time.isoformat() if row.start_time else None,
                    'end_time': row.end_time.isoformat() if row.end_time else None,
                    'status': row.status,
                    'error': row.error,
                    'config_hash': row.config_hash
                })
            
            return jsonify(runs)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/reset-prompts', methods=['POST'])
def reset_prompts():
    """Reset prompts to v0 baseline for AUTO mode configurations"""
    try:
        config_hash = get_current_config_hash()
        
        # Check if this config is in AUTO mode
        with engine.connect() as conn:
            config_result = conn.execute(text("""
                SELECT prompt_mode, forced_prompt_version
                FROM run_configurations
                WHERE config_hash = :config_hash
            """), {"config_hash": config_hash}).fetchone()
            
            if not config_result:
                return jsonify({'error': 'Configuration not found'}), 400
                
            if config_result.prompt_mode != 'auto':
                return jsonify({
                    'error': f'Cannot reset prompts for FIXED mode configuration (currently FIXED v{config_result.forced_prompt_version})'
                }), 400

        # Ensure v0 templates match current code defaults before toggling
        try:
            importlib.reload(default_prompts_module)
            latest_defaults = default_prompts_module.DEFAULT_PROMPTS
            with engine.begin() as conn:
                for agent_type, payload in latest_defaults.items():
                    _ensure_v0_prompt(conn, agent_type, config_hash, payload)
                    _ensure_v0_prompt(conn, agent_type, 'global', payload)
        except Exception as e:
            print(f"⚠️  Failed to sync v0 prompts with defaults: {e}")

        # Reset prompt systems with proper error handling
        try:
            with engine.begin() as conn:
                # Reset main prompt_versions table
                conn.execute(text("""
                    UPDATE prompt_versions 
                    SET is_active = FALSE
                    WHERE config_hash = :config_hash
                """), {"config_hash": config_hash})
                
                # Activate only v0 prompts in main table
                updated_prompts = conn.execute(text("""
                    UPDATE prompt_versions 
                    SET is_active = TRUE
                    WHERE config_hash = :config_hash AND version = 0
                """), {"config_hash": config_hash})
                
                if updated_prompts.rowcount == 0:
                    return jsonify({'error': 'No v0 baseline prompts found for this configuration'}), 400
                
                # Get the updated prompt versions for confirmation
                active_prompts = conn.execute(text("""
                    SELECT agent_type, version
                    FROM prompt_versions
                    WHERE config_hash = :config_hash AND is_active = TRUE
                    ORDER BY agent_type
                """), {"config_hash": config_hash}).fetchall()
                
                prompt_info = {row.agent_type: row.version for row in active_prompts}
                
        except Exception as e:
            print(f"❌ Main prompt reset failed: {e}")
            return jsonify({'error': f'Failed to reset main prompts: {str(e)}'}), 500
        
        # Reset feedback system in separate transaction to avoid conflicts
        try:
            with engine.begin() as conn:
                # Try config-isolated reset first (if schema has been updated)
                feedback_reset = conn.execute(text("""
                    UPDATE ai_agent_prompts 
                    SET is_active = FALSE
                    WHERE agent_type IN ('SummarizerAgent', 'DeciderAgent') 
                    AND (config_hash = :config_hash OR config_hash IS NULL)
                """), {"config_hash": config_hash})
                
                print(f"✅ Reset feedback system prompts ({feedback_reset.rowcount} affected)")
                
        except Exception as e:
            print(f"⚠️  Feedback system reset failed: {e}")
            # Don't fail the whole operation if feedback reset fails
        
        # Reset unified table in separate transaction
        try:
            with engine.begin() as conn:
                unified_reset = conn.execute(text("""
                    UPDATE unified_prompts 
                    SET is_active = FALSE
                    WHERE config_hash = :config_hash
                """), {"config_hash": config_hash})
                
                if unified_reset.rowcount > 0:
                    conn.execute(text("""
                        UPDATE unified_prompts 
                        SET is_active = TRUE
                        WHERE config_hash = :config_hash AND version = 0
                    """), {"config_hash": config_hash})
                    print(f"✅ Reset unified prompts table ({unified_reset.rowcount} prompts)")
                    
        except Exception as e:
            print(f"⚠️  Unified table reset failed (table may not exist): {e}")
            
            return jsonify({
                'success': True,
                'message': f'Prompts reset to v0 baseline. Summarizer: v{prompt_info.get("SummarizerAgent", "?")}, Decider: v{prompt_info.get("DeciderAgent", "?")}',
                'prompt_versions': prompt_info
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset-portfolio', methods=['POST'])
def reset_portfolio():
    """Reset portfolio to either the live Schwab snapshot or simulation baseline."""
    try:
        config_hash = get_current_config_hash()
        current_mode = get_trading_mode()
        use_live = getattr(trading_interface, 'schwab_enabled', False) and (
            os.getenv('DAI_SCHWAB_LIVE_VIEW', '0') in {'1', 'true', 'True'}
            or current_mode in {'live', 'real_world'}
        )
        schwab_snapshot = None

        if use_live:
            try:
                snapshot = trading_interface.sync_schwab_positions()
                if snapshot.get('status') == 'success':
                    schwab_snapshot = snapshot
                else:
                    print(f"⚠️ Schwab reset snapshot unavailable: {snapshot.get('message')}")
            except Exception as e:
                print(f"⚠️ Schwab reset snapshot error: {e}")

        with engine.begin() as conn:
            current_holdings = conn.execute(text("""
                SELECT ticker, shares, purchase_price, current_price, total_value, current_value, gain_loss
                FROM holdings
                WHERE is_active = TRUE AND ticker != 'CASH' AND config_hash = :config_hash
            """), {"config_hash": config_hash}).fetchall()

            for holding in current_holdings:
                if holding.shares > 0:
                    conn.execute(text("""
                        INSERT INTO trade_outcomes (
                            ticker, sell_timestamp, purchase_price, sell_price,
                            shares, gain_loss_amount, gain_loss_percentage,
                            hold_duration_days, original_reason, sell_reason, outcome_category, config_hash
                        ) VALUES (
                            :ticker, CURRENT_TIMESTAMP, :purchase_price, :current_price,
                            :shares, :gain_loss,
                            CASE WHEN :total_value > 0 THEN (:gain_loss / :total_value * 100) ELSE 0 END,
                            0, 'Portfolio reset', 'Portfolio reset', 'break_even', :config_hash
                        )
                    """), {
                        "ticker": holding.ticker,
                        "purchase_price": float(holding.purchase_price),
                        "current_price": float(holding.current_price),
                        "shares": float(holding.shares),
                        "gain_loss": float(holding.gain_loss),
                        "total_value": float(holding.total_value),
                        "config_hash": config_hash
                    })

            conn.execute(text("""
                UPDATE holdings
                SET is_active = FALSE, shares = 0, current_value = 0, gain_loss = 0
                WHERE ticker != 'CASH' AND config_hash = :config_hash
            """), {"config_hash": config_hash})

            if not schwab_snapshot:
                conn.execute(text("""
                    DELETE FROM holdings WHERE ticker = 'CASH' AND config_hash = :config_hash
                """), {"config_hash": config_hash})
                conn.execute(text("""
                    INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price,
                                          purchase_timestamp, current_price_timestamp, total_value, current_value,
                                          gain_loss, reason, is_active)
                    VALUES (:config_hash, 'CASH', 1, 10000, 10000, now(), now(), 10000, 10000, 0, 'Reset to simulation cash', TRUE)
                """), {"config_hash": config_hash})

            conn.execute(text("""
                DELETE FROM agent_feedback WHERE config_hash = :config_hash
            """), {"config_hash": config_hash})

            conn.execute(text("""
                DELETE FROM trade_outcomes WHERE config_hash = :config_hash
            """), {"config_hash": config_hash})

            conn.execute(text("""
                DELETE FROM portfolio_history WHERE config_hash = :config_hash
            """), {"config_hash": config_hash})

        message = "Portfolio reset to simulation baseline ($10,000)."

        if not schwab_snapshot:
            with engine.begin() as conn:
                agent_types = ['SummarizerAgent', 'DeciderAgent']
                for agent_type in agent_types:
                    v4_exists = conn.execute(text("""
                        SELECT id FROM prompt_versions 
                        WHERE agent_type = :agent_type AND version = 4
                    """), {"agent_type": agent_type}).fetchone()

                    if v4_exists:
                        conn.execute(text("""
                            UPDATE prompt_versions 
                            SET is_active = FALSE
                            WHERE agent_type = :agent_type
                        """), {"agent_type": agent_type})
                        conn.execute(text("""
                            UPDATE prompt_versions 
                            SET is_active = TRUE
                            WHERE agent_type = :agent_type AND version = 4
                        """), {"agent_type": agent_type})

        if schwab_snapshot:
            positions = schwab_snapshot.get('positions', [])
            processed = []
            total_invested = 0.0
            total_current = 0.0
            for position in positions:
                shares = float(position.get('shares') or 0)
                avg_price = float(position.get('average_price') or 0)
                current_price = float(position.get('current_price') or 0)
                total_cost = float(position.get('total_value') or (shares * avg_price))
                market_value = float(position.get('market_value') or (shares * current_price))
                if avg_price == 0 and shares > 0:
                    avg_price = total_cost / shares if total_cost else current_price
                gain_loss = market_value - total_cost
                processed.append({
                    "ticker": position.get('symbol', '-').upper(),
                    "shares": shares,
                    "purchase_price": avg_price,
                    "current_price": current_price,
                    "total_value": total_cost,
                    "current_value": market_value,
                    "gain_loss": gain_loss,
                    "reason": "Schwab synced position"
                })
                total_invested += total_cost
                total_current += market_value

            cash_balance = float(schwab_snapshot.get('cash_balance', 0))
            total_portfolio_value = total_current + cash_balance
            total_profit_loss = total_current - total_invested

            _sync_holdings_with_database(config_hash, processed, cash_balance)
            _record_live_portfolio_snapshot(
                config_hash,
                total_portfolio_value,
                cash_balance,
                total_invested,
                total_profit_loss,
                processed,
            )

            message = "Portfolio reset to live Schwab snapshot."

        return jsonify({"success": True, "message": message})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/schwab/holdings')
def get_schwab_holdings():
    """Get current Schwab holdings and portfolio data (READ-ONLY)"""
    import pytz
    
    # Check if we're in read-only test mode
    readonly_mode = os.environ.get('DAI_SCHWAB_READONLY', '0') == '1'
    
    if not SCHWAB_ENABLED:
        return jsonify({
            'error': 'Schwab integration not available. Run: pip install schwab-api',
            'enabled': False,
            'readonly_mode': readonly_mode
        })
    
    try:
        # Get Schwab account data (read-only operation)
        schwab_data = trading_interface.sync_schwab_positions()
        schwab_data['enabled'] = True
        schwab_data['readonly_mode'] = readonly_mode
        schwab_data['live_trading_enabled'] = (trading_interface.trading_mode in {"live", "real_world"}) and not readonly_mode
        schwab_data.setdefault('account_info', {})
        if readonly_mode:
            schwab_data['account_info'].setdefault('account_hash', schwab_client.account_hash if hasattr(schwab_client, "account_hash") else None)
        
        # Add safety warning if in read-only mode
        if readonly_mode:
            schwab_data['warning'] = '🔒 READ-ONLY MODE: No trades will be executed'
        
        # Add timestamp
        pacific_tz = pytz.timezone('US/Pacific')
        now = datetime.now(pacific_tz)
        schwab_data['last_updated'] = now.strftime('%m/%d/%Y, %I:%M:%S %p %Z')
        
        return jsonify(schwab_data)
    except Exception as e:
        return jsonify({
            'error': str(e),
            'enabled': True,
            'readonly_mode': readonly_mode,
            'status': 'error'
        })

@app.route('/api/schwab/account-info')
def get_schwab_account_info():
    """Get Schwab account information"""
    if not SCHWAB_ENABLED:
        return jsonify({
            'error': 'Schwab integration not available',
            'enabled': False
        })
    
    try:
        from schwab_client import schwab_client
        account_info = schwab_client.get_account_info()
        if account_info:
            return jsonify({
                'status': 'success',
                'account_info': account_info,
                'enabled': True
            })
        else:
            return jsonify({
                'error': 'Could not retrieve account information',
                'enabled': True,
                'status': 'error'
            })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'enabled': True,
            'status': 'error'
        })

@app.route('/schwab')
def schwab_dashboard():
    """Render the Schwab holdings dashboard"""
    return render_template('schwab_dashboard.html')

if __name__ == "__main__":
    port = int(os.environ.get('DAI_PORT', 8080))
    print(f"🚀 Starting dashboard server on port {port} (trading_mode={get_trading_mode()})")
    app.run(debug=True, port=port)
