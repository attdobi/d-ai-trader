#!/usr/bin/env python3
"""
Initialize all d-ai-trader database tables up front.

This script is intentionally idempotent and safe to run multiple times.
It creates/updates schema pieces that are otherwise created lazily across the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from sqlalchemy import text

from config import engine, get_current_config_hash
from initialize_prompts import DEFAULT_PROMPTS


@dataclass
class InitStats:
    created_tables: int = 0
    existing_tables: int = 0
    added_columns: int = 0
    existing_columns: int = 0
    added_constraints: int = 0
    existing_constraints: int = 0
    seeded_prompts: int = 0
    updated_prompts: int = 0
    skipped_prompts: int = 0


def table_exists(conn, table_name: str) -> bool:
    return conn.execute(
        text("SELECT to_regclass(:tbl)") ,
        {"tbl": table_name},
    ).scalar() is not None


def column_exists(conn, table_name: str, column_name: str) -> bool:
    return conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).fetchone() is not None


def constraint_exists(conn, constraint_name: str) -> bool:
    return conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.table_constraints
            WHERE constraint_schema = 'public'
              AND constraint_name = :constraint_name
            """
        ),
        {"constraint_name": constraint_name},
    ).fetchone() is not None


def ensure_table(conn, stats: InitStats, table_name: str, create_sql: str) -> None:
    existed = table_exists(conn, table_name)
    conn.execute(text(create_sql))
    if existed:
        stats.existing_tables += 1
        print(f"ℹ️  Table exists: {table_name}")
    else:
        stats.created_tables += 1
        print(f"✅ Created table: {table_name}")


def ensure_column(conn, stats: InitStats, table_name: str, column_name: str, alter_sql: str) -> None:
    existed = column_exists(conn, table_name, column_name)
    conn.execute(text(alter_sql))
    if existed:
        stats.existing_columns += 1
        print(f"   ↪ Column exists: {table_name}.{column_name}")
    else:
        stats.added_columns += 1
        print(f"   ✅ Added column: {table_name}.{column_name}")


def ensure_constraint(conn, stats: InitStats, constraint_name: str, alter_sql: str) -> None:
    existed = constraint_exists(conn, constraint_name)
    if existed:
        stats.existing_constraints += 1
        print(f"   ↪ Constraint exists: {constraint_name}")
        return

    try:
        conn.execute(text(alter_sql))
        stats.added_constraints += 1
        print(f"   ✅ Added constraint: {constraint_name}")
    except Exception as exc:
        # If an equivalent constraint already exists under a different name,
        # keep going to preserve idempotence.
        stats.existing_constraints += 1
        print(f"   ⚠️  Could not add constraint {constraint_name}: {exc}")


def _normalized_prompt_rows() -> Dict[str, Dict[str, str]]:
    rows: Dict[str, Dict[str, str]] = {}
    for agent_type, payload in DEFAULT_PROMPTS.items():
        user_prompt = (payload.get("user_prompt_template") or payload.get("user_prompt") or "").strip()
        system_prompt = (payload.get("system_prompt") or "").strip()
        description = (payload.get("description") or "v0 baseline prompt").strip()
        strategy_directives = (payload.get("strategy_directives") or "").strip()
        soul = (payload.get("soul") or "").strip()
        memory = (payload.get("memory") or "").strip()

        if not user_prompt or not system_prompt:
            print(f"⚠️  Skipping malformed prompt payload for {agent_type}")
            continue

        rows[agent_type] = {
            "user_prompt_template": user_prompt,
            "system_prompt": system_prompt,
            "strategy_directives": strategy_directives,
            "description": description,
            "soul": soul,
            "memory": memory,
        }

    return rows


def seed_v0_prompts(conn, stats: InitStats, config_hash: str) -> None:
    prompt_rows = _normalized_prompt_rows()

    for agent_type, payload in prompt_rows.items():
        existing = conn.execute(
            text(
                """
                SELECT id, system_prompt, user_prompt_template, strategy_directives, description, is_active, soul, memory
                FROM prompt_versions
                WHERE agent_type = :agent_type
                  AND version = 0
                  AND config_hash = :config_hash
                LIMIT 1
                """
            ),
            {"agent_type": agent_type, "config_hash": config_hash},
        ).fetchone()

        if existing is None:
            conn.execute(
                text(
                    """
                    INSERT INTO prompt_versions (
                        agent_type,
                        version,
                        system_prompt,
                        user_prompt_template,
                        strategy_directives,
                        description,
                        created_by,
                        is_active,
                        config_hash,
                        soul,
                        memory
                    ) VALUES (
                        :agent_type,
                        0,
                        :system_prompt,
                        :user_prompt_template,
                        :strategy_directives,
                        :description,
                        'init_database',
                        TRUE,
                        :config_hash,
                        :soul,
                        :memory
                    )
                    """
                ),
                {
                    "agent_type": agent_type,
                    "system_prompt": payload["system_prompt"],
                    "user_prompt_template": payload["user_prompt_template"],
                    "strategy_directives": payload["strategy_directives"],
                    "description": payload["description"],
                    "config_hash": config_hash,
                    "soul": payload.get("soul", ""),
                    "memory": payload.get("memory", ""),
                },
            )
            stats.seeded_prompts += 1
            print(f"   ✅ Seeded v0 prompt: {agent_type} ({config_hash})")
            continue

        needs_update = (
            (existing.system_prompt or "") != payload["system_prompt"]
            or (existing.user_prompt_template or "") != payload["user_prompt_template"]
            or (existing.strategy_directives or "") != payload["strategy_directives"]
            or (existing.description or "") != payload["description"]
            or not bool(existing.is_active)
        )

        # Seed soul/memory into existing rows only if DB is empty and payload has content
        seed_soul = not (existing.soul or "").strip() and payload.get("soul", "").strip()
        seed_memory = not (existing.memory or "").strip() and payload.get("memory", "").strip()

        if needs_update or seed_soul or seed_memory:
            update_fields = {
                "id": existing.id,
                "system_prompt": payload["system_prompt"],
                "user_prompt_template": payload["user_prompt_template"],
                "strategy_directives": payload["strategy_directives"],
                "description": payload["description"],
            }

            # Build dynamic SET clause
            set_parts = [
                "system_prompt = :system_prompt",
                "user_prompt_template = :user_prompt_template",
                "strategy_directives = :strategy_directives",
                "description = :description",
                "created_by = 'init_database'",
                "is_active = TRUE",
                "created_at = CURRENT_TIMESTAMP",
            ]

            if seed_soul:
                set_parts.append("soul = :soul")
                update_fields["soul"] = payload["soul"]
            if seed_memory:
                set_parts.append("memory = :memory")
                update_fields["memory"] = payload["memory"]

            conn.execute(
                text(f"UPDATE prompt_versions SET {', '.join(set_parts)} WHERE id = :id"),
                update_fields,
            )
            stats.updated_prompts += 1
            print(f"   🔄 Updated v0 prompt: {agent_type} ({config_hash})")
        else:
            stats.skipped_prompts += 1
            print(f"   ↪ Prompt already up-to-date: {agent_type} ({config_hash})")


def initialize_database() -> None:
    stats = InitStats()

    # This is the active runtime config hash for the current process profile.
    current_config_hash = get_current_config_hash()

    print("🗄️  Initializing d-ai-trader database schema...")
    print(f"🔑 Active config hash: {current_config_hash}")

    with engine.begin() as conn:
        # 1) Core configuration table
        ensure_table(
            conn,
            stats,
            "run_configurations",
            """
            CREATE TABLE IF NOT EXISTS run_configurations (
                config_hash TEXT PRIMARY KEY,
                gpt_model TEXT NOT NULL,
                prompt_mode TEXT NOT NULL,
                forced_prompt_version INTEGER,
                trading_mode TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )

        # 2) Context/summaries tables
        ensure_table(
            conn,
            stats,
            "agent_contexts",
            """
            CREATE TABLE IF NOT EXISTS agent_contexts (
                id SERIAL PRIMARY KEY,
                agent_name VARCHAR NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                content TEXT NOT NULL
            )
            """,
        )

        ensure_table(
            conn,
            stats,
            "summaries",
            """
            CREATE TABLE IF NOT EXISTS summaries (
                id SERIAL PRIMARY KEY,
                config_hash TEXT NOT NULL,
                agent TEXT,
                timestamp TIMESTAMP,
                run_id TEXT,
                data JSONB
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "summaries",
            "config_hash",
            "ALTER TABLE summaries ADD COLUMN IF NOT EXISTS config_hash TEXT",
        )
        ensure_column(
            conn,
            stats,
            "summaries",
            "run_id",
            "ALTER TABLE summaries ADD COLUMN IF NOT EXISTS run_id TEXT",
        )
        ensure_column(
            conn,
            stats,
            "summaries",
            "data",
            "ALTER TABLE summaries ADD COLUMN IF NOT EXISTS data JSONB",
        )

        # 3) Process/run tracking
        ensure_table(
            conn,
            stats,
            "processed_summaries",
            """
            CREATE TABLE IF NOT EXISTS processed_summaries (
                id SERIAL PRIMARY KEY,
                summary_id INTEGER NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_by TEXT NOT NULL,
                run_id TEXT,
                config_hash TEXT
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "processed_summaries",
            "config_hash",
            "ALTER TABLE processed_summaries ADD COLUMN IF NOT EXISTS config_hash TEXT",
        )

        ensure_table(
            conn,
            stats,
            "system_runs",
            """
            CREATE TABLE IF NOT EXISTS system_runs (
                id SERIAL PRIMARY KEY,
                run_type TEXT NOT NULL,
                start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP,
                status TEXT DEFAULT 'running',
                details JSONB,
                config_hash TEXT
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "system_runs",
            "config_hash",
            "ALTER TABLE system_runs ADD COLUMN IF NOT EXISTS config_hash TEXT",
        )

        # 4) Trading/portfolio tables
        ensure_table(
            conn,
            stats,
            "holdings",
            """
            CREATE TABLE IF NOT EXISTS holdings (
                id SERIAL PRIMARY KEY,
                config_hash TEXT NOT NULL,
                ticker TEXT NOT NULL,
                shares FLOAT,
                purchase_price FLOAT,
                current_price FLOAT,
                purchase_timestamp TIMESTAMP,
                current_price_timestamp TIMESTAMP,
                total_value FLOAT,
                current_value FLOAT,
                gain_loss FLOAT,
                reason TEXT,
                is_active BOOLEAN
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "holdings",
            "config_hash",
            "ALTER TABLE holdings ADD COLUMN IF NOT EXISTS config_hash TEXT",
        )
        ensure_constraint(
            conn,
            stats,
            "holdings_config_ticker_unique",
            "ALTER TABLE holdings ADD CONSTRAINT holdings_config_ticker_unique UNIQUE (config_hash, ticker)",
        )

        ensure_table(
            conn,
            stats,
            "portfolio_history",
            """
            CREATE TABLE IF NOT EXISTS portfolio_history (
                id SERIAL PRIMARY KEY,
                config_hash VARCHAR(50) NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_portfolio_value FLOAT,
                cash_balance FLOAT,
                total_invested FLOAT,
                total_profit_loss FLOAT,
                percentage_gain FLOAT,
                holdings_snapshot JSONB
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "portfolio_history",
            "config_hash",
            "ALTER TABLE portfolio_history ADD COLUMN IF NOT EXISTS config_hash VARCHAR(50)",
        )

        ensure_table(
            conn,
            stats,
            "trade_decisions",
            """
            CREATE TABLE IF NOT EXISTS trade_decisions (
                id SERIAL PRIMARY KEY,
                config_hash VARCHAR(50) NOT NULL,
                run_id TEXT,
                timestamp TIMESTAMP,
                data JSONB
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "trade_decisions",
            "config_hash",
            "ALTER TABLE trade_decisions ADD COLUMN IF NOT EXISTS config_hash VARCHAR(50)",
        )
        ensure_column(
            conn,
            stats,
            "trade_decisions",
            "run_id",
            "ALTER TABLE trade_decisions ADD COLUMN IF NOT EXISTS run_id TEXT",
        )

        ensure_table(
            conn,
            stats,
            "momentum_snapshots",
            """
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
            """,
        )
        ensure_column(
            conn,
            stats,
            "momentum_snapshots",
            "run_id",
            "ALTER TABLE momentum_snapshots ADD COLUMN IF NOT EXISTS run_id TEXT",
        )

        ensure_table(
            conn,
            stats,
            "live_portfolio_baselines",
            """
            CREATE TABLE IF NOT EXISTS live_portfolio_baselines (
                config_hash TEXT PRIMARY KEY,
                baseline_value FLOAT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )

        # 5) Feedback/evolution tables
        ensure_table(
            conn,
            stats,
            "trade_outcomes",
            """
            CREATE TABLE IF NOT EXISTS trade_outcomes (
                id SERIAL PRIMARY KEY,
                config_hash VARCHAR(50) NOT NULL,
                ticker TEXT NOT NULL,
                sell_timestamp TIMESTAMP NOT NULL,
                purchase_price FLOAT NOT NULL,
                sell_price FLOAT NOT NULL,
                shares FLOAT NOT NULL,
                gain_loss_amount FLOAT NOT NULL,
                gain_loss_percentage FLOAT NOT NULL,
                hold_duration_days INTEGER NOT NULL,
                original_reason TEXT,
                sell_reason TEXT,
                outcome_category TEXT CHECK (
                    outcome_category IN (
                        'significant_profit',
                        'moderate_profit',
                        'break_even',
                        'moderate_loss',
                        'significant_loss'
                    )
                ),
                market_context JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "trade_outcomes",
            "config_hash",
            "ALTER TABLE trade_outcomes ADD COLUMN IF NOT EXISTS config_hash VARCHAR(50)",
        )

        ensure_table(
            conn,
            stats,
            "agent_feedback",
            """
            CREATE TABLE IF NOT EXISTS agent_feedback (
                id SERIAL PRIMARY KEY,
                analysis_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                config_hash VARCHAR(50),
                lookback_period_days INTEGER NOT NULL,
                total_trades_analyzed INTEGER NOT NULL,
                success_rate FLOAT NOT NULL,
                avg_profit_percentage FLOAT NOT NULL,
                top_performing_patterns JSONB,
                underperforming_patterns JSONB,
                recommended_adjustments JSONB,
                summarizer_feedback TEXT,
                decider_feedback TEXT
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "agent_feedback",
            "config_hash",
            "ALTER TABLE agent_feedback ADD COLUMN IF NOT EXISTS config_hash VARCHAR(50)",
        )

        ensure_table(
            conn,
            stats,
            "agent_instruction_updates",
            """
            CREATE TABLE IF NOT EXISTS agent_instruction_updates (
                id SERIAL PRIMARY KEY,
                agent_type TEXT NOT NULL,
                update_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                original_instructions TEXT NOT NULL,
                updated_instructions TEXT NOT NULL,
                reason_for_update TEXT NOT NULL,
                performance_trigger JSONB,
                config_hash VARCHAR(50)
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "agent_instruction_updates",
            "config_hash",
            "ALTER TABLE agent_instruction_updates ADD COLUMN IF NOT EXISTS config_hash VARCHAR(50)",
        )

        ensure_table(
            conn,
            stats,
            "ai_agent_feedback_responses",
            """
            CREATE TABLE IF NOT EXISTS ai_agent_feedback_responses (
                id SERIAL PRIMARY KEY,
                agent_type TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_prompt TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                ai_response TEXT NOT NULL,
                context_data JSONB,
                performance_metrics JSONB,
                feedback_category TEXT,
                is_manual_request BOOLEAN DEFAULT FALSE,
                config_hash VARCHAR(50)
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "ai_agent_feedback_responses",
            "config_hash",
            "ALTER TABLE ai_agent_feedback_responses ADD COLUMN IF NOT EXISTS config_hash VARCHAR(50)",
        )

        # ai_agent_prompts references ai_agent_feedback_responses(id)
        ensure_table(
            conn,
            stats,
            "ai_agent_prompts",
            """
            CREATE TABLE IF NOT EXISTS ai_agent_prompts (
                id SERIAL PRIMARY KEY,
                agent_type TEXT NOT NULL,
                prompt_version INTEGER,
                version INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_prompt TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                description TEXT,
                is_active BOOLEAN DEFAULT FALSE,
                created_by TEXT DEFAULT 'system',
                triggered_by_feedback_id INTEGER REFERENCES ai_agent_feedback_responses(id),
                config_hash VARCHAR(50)
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "ai_agent_prompts",
            "version",
            "ALTER TABLE ai_agent_prompts ADD COLUMN IF NOT EXISTS version INTEGER",
        )
        ensure_column(
            conn,
            stats,
            "ai_agent_prompts",
            "config_hash",
            "ALTER TABLE ai_agent_prompts ADD COLUMN IF NOT EXISTS config_hash VARCHAR(50)",
        )

        # 6) Unified prompt versions table (used by prompt_manager / dashboard)
        ensure_table(
            conn,
            stats,
            "prompt_versions",
            """
            CREATE TABLE IF NOT EXISTS prompt_versions (
                id SERIAL PRIMARY KEY,
                agent_type TEXT NOT NULL,
                version INTEGER NOT NULL,
                system_prompt TEXT NOT NULL,
                user_prompt_template TEXT NOT NULL,
                description TEXT,
                created_by TEXT DEFAULT 'system',
                is_active BOOLEAN DEFAULT FALSE,
                config_hash TEXT NOT NULL DEFAULT 'global',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
        ensure_column(
            conn,
            stats,
            "prompt_versions",
            "config_hash",
            "ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS config_hash TEXT DEFAULT 'global'",
        )
        ensure_column(
            conn,
            stats,
            "prompt_versions",
            "user_prompt_template",
            "ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS user_prompt_template TEXT",
        )
        ensure_column(
            conn,
            stats,
            "prompt_versions",
            "created_at",
            "ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        )
        ensure_column(
            conn,
            stats,
            "prompt_versions",
            "strategy_directives",
            "ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS strategy_directives TEXT",
        )
        ensure_column(
            conn,
            stats,
            "prompt_versions",
            "soul",
            "ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS soul TEXT DEFAULT ''",
        )
        ensure_column(
            conn,
            stats,
            "prompt_versions",
            "memory",
            "ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS memory TEXT DEFAULT ''",
        )

        # Backfill legacy prompt_versions rows where config_hash was null.
        conn.execute(text("UPDATE prompt_versions SET config_hash = 'global' WHERE config_hash IS NULL OR config_hash = ''"))

        # Backfill legacy user_prompt -> user_prompt_template if present.
        if column_exists(conn, "prompt_versions", "user_prompt"):
            conn.execute(text(
                """
                UPDATE prompt_versions
                SET user_prompt_template = COALESCE(user_prompt_template, user_prompt)
                WHERE user_prompt_template IS NULL
                """
            ))

        ensure_constraint(
            conn,
            stats,
            "prompt_versions_agent_version_config_unique",
            "ALTER TABLE prompt_versions ADD CONSTRAINT prompt_versions_agent_version_config_unique UNIQUE (agent_type, version, config_hash)",
        )

        # Backfill ai_agent_prompts.version from legacy prompt_version if available.
        if column_exists(conn, "ai_agent_prompts", "prompt_version"):
            conn.execute(text(
                """
                UPDATE ai_agent_prompts
                SET version = COALESCE(version, prompt_version)
                WHERE version IS NULL
                """
            ))

        ensure_table(
            conn,
            stats,
            "model_transitions",
            """
            CREATE TABLE IF NOT EXISTS model_transitions (
                id SERIAL PRIMARY KEY,
                config_hash TEXT NOT NULL,
                model_name TEXT NOT NULL,
                started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at TIMESTAMP,
                notes TEXT
            )
            """,
        )
        # Index for fast lookups by config_hash
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_model_transitions_hash
            ON model_transitions(config_hash)
        """))

        # 7) Seed v0 baseline prompts from initialize_prompts.py
        print("🧠 Seeding v0 baseline prompts...")
        seed_v0_prompts(conn, stats, "global")
        seed_v0_prompts(conn, stats, current_config_hash)

        # Backfill soul/memory on ALL active prompts that have empty values
        # This handles production DBs where active prompts (e.g. v15) were created
        # before soul/memory columns existed
        prompt_rows = _normalized_prompt_rows()
        _AGENT_FILE_MAP = {
            "DeciderAgent": "decider",
            "SummarizerAgent": "summarizer",
            "FeedbackAgent": "feedback",
            "feedback_analyzer": "feedback",
        }
        backfilled = 0
        for agent_type, file_name in _AGENT_FILE_MAP.items():
            default_soul = prompt_rows.get(agent_type, {}).get("soul", "")
            default_memory = prompt_rows.get(agent_type, {}).get("memory", "")
            if not default_soul and not default_memory:
                continue

            # Find active prompts with empty soul/memory
            active_rows = conn.execute(text("""
                SELECT id, soul, memory FROM prompt_versions
                WHERE agent_type = :agent_type AND is_active = TRUE
                  AND (COALESCE(soul, '') = '' OR COALESCE(memory, '') = '')
            """), {"agent_type": agent_type}).fetchall()

            for row in active_rows:
                updates = {}
                if not (row.soul or "").strip() and default_soul:
                    updates["soul"] = default_soul
                if not (row.memory or "").strip() and default_memory:
                    updates["memory"] = default_memory
                if updates:
                    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
                    updates["id"] = row.id
                    conn.execute(text(f"UPDATE prompt_versions SET {set_clauses} WHERE id = :id"), updates)
                    backfilled += 1
                    print(f"   🧠 Backfilled soul/memory for {agent_type} (id={row.id})")

        if backfilled:
            print(f"   🧠 Backfilled {backfilled} active prompts with default soul/memory")

    print("\n📋 Database initialization summary")
    print("---------------------------------")
    print(f"Tables created:        {stats.created_tables}")
    print(f"Tables already existed:{stats.existing_tables}")
    print(f"Columns added:         {stats.added_columns}")
    print(f"Columns already exist: {stats.existing_columns}")
    print(f"Constraints added:     {stats.added_constraints}")
    print(f"Constraints existing:  {stats.existing_constraints}")
    print(f"Prompts seeded:        {stats.seeded_prompts}")
    print(f"Prompts updated:       {stats.updated_prompts}")
    print(f"Prompts unchanged:     {stats.skipped_prompts}")
    print("✅ Database initialization complete.")


if __name__ == "__main__":
    initialize_database()
