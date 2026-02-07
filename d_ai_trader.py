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

#!/usr/bin/env python3
"""
D-AI-Trader Unified Automation System

This script orchestrates the entire trading system with SEQUENTIAL execution:
- STEP 1: Summarizer agents run hourly (8:25am-5:25pm ET weekdays, 3pm ET weekends)
- STEP 2: Decider agent runs immediately after Step 1 (during market hours only) using fresh summaries
- STEP 3: Feedback agent runs once daily after market close (4:30pm ET)

This ensures decider always uses the most recent summaries, not stale data.
"""

import os
import sys
import time
import json
import schedule
import logging
import threading
from datetime import datetime, timedelta
import pytz
from sqlalchemy import text
from config import engine, PromptManager, session, openai, set_gpt_model, get_trading_mode
from feedback_agent import TradeOutcomeTracker
from trading_interface import trading_interface

# Apply model from environment if specified
if _os.environ.get("DAI_GPT_MODEL"):
    set_gpt_model(_os.environ["DAI_GPT_MODEL"])

# Import the existing modules
import main as summarizer_main
import decider_agent as decider
import feedback_agent as feedback_agent_module

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('d-ai-trader.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Timezone configuration
def _load_local_timezone():
    tz_name = os.getenv("DAI_LOCAL_TIMEZONE") or os.getenv("TZ")
    if tz_name:
        try:
            return pytz.timezone(tz_name)
        except Exception as exc:
            logger.warning(f"Invalid timezone '{tz_name}' in env; falling back to system local. Error: {exc}")
    try:
        return datetime.now().astimezone().tzinfo
    except Exception:
        return pytz.timezone('UTC')

LOCAL_TIMEZONE = _load_local_timezone()
LOCAL_TZ_ABBR = datetime.now(LOCAL_TIMEZONE).tzname() or "local"
EASTERN_TIMEZONE = pytz.timezone('US/Eastern')

# Market hours configuration (Eastern Time - market hours are always ET)
MARKET_OPEN_TIME = "09:30"
MARKET_CLOSE_TIME = "16:00"
SUMMARIZER_START_TIME = "08:25"
SUMMARIZER_END_TIME = "17:25"
WEEKEND_SUMMARIZER_TIME = "15:00"  # 3pm ET

_MANUAL_DECIDER_SKIP_DEADLINE = None
_MANUAL_DECIDER_SKIP_LOCK = threading.Lock()


def mark_manual_decider_window(minutes=30):
    """Hold off scheduled cycles for a fixed window after a manual decider run."""
    global _MANUAL_DECIDER_SKIP_DEADLINE
    with _MANUAL_DECIDER_SKIP_LOCK:
        _MANUAL_DECIDER_SKIP_DEADLINE = datetime.utcnow() + timedelta(minutes=minutes)


def manual_decider_skip_seconds():
    """Return remaining seconds in the manual-decider cooldown window (0 if inactive)."""
    global _MANUAL_DECIDER_SKIP_DEADLINE
    with _MANUAL_DECIDER_SKIP_LOCK:
        if _MANUAL_DECIDER_SKIP_DEADLINE is None:
            return 0.0
        now = datetime.utcnow()
        if now >= _MANUAL_DECIDER_SKIP_DEADLINE:
            _MANUAL_DECIDER_SKIP_DEADLINE = None
            return 0.0
        return (_MANUAL_DECIDER_SKIP_DEADLINE - now).total_seconds()


class DAITraderOrchestrator:
    def __init__(self):
        self.prompt_manager = PromptManager(client=openai, session=session)
        self.last_processed_summary_id = None
        self.initialize_database()
        self._market_open_run_date = None
        self._startup_cycle_completed = False
        self._startup_date_et = datetime.now(EASTERN_TIMEZONE).date()
        self._startup_time_et = datetime.now(EASTERN_TIMEZONE)
        self._cadence_minutes = int(os.environ.get('DAI_CADENCE_MINUTES', '180'))
        self._next_cadence_run_et = None
        
    def initialize_database(self):
        """Initialize database tables for tracking processed summaries"""
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS processed_summaries (
                    id SERIAL PRIMARY KEY,
                    summary_id INTEGER NOT NULL,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_by TEXT NOT NULL,
                    run_id TEXT
                )
            """))
            
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS system_runs (
                    id SERIAL PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMP,
                    status TEXT DEFAULT 'running',
                    details JSONB
                )
            """))
    
    def is_market_open(self):
        """Check if the market is currently open (M-F, 9:30am-4pm ET)"""
        # Get current time in local tz, convert to Eastern for market hours check
        now_local = datetime.now(LOCAL_TIMEZONE)
        now_eastern = now_local.astimezone(EASTERN_TIMEZONE)
        
        # Check if it's a weekday (Monday = 0, Sunday = 6)
        if now_eastern.weekday() >= 5:  # Saturday or Sunday
            return False
            
        # Check if it's within market hours (Eastern Time)
        market_open = now_eastern.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_eastern.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= now_eastern <= market_close
    
    def is_summarizer_time(self):
        """Check if it's time to run summarizers"""
        # Get current time in local tz, convert to Eastern for time checks
        now_local = datetime.now(LOCAL_TIMEZONE)
        now_eastern = now_local.astimezone(EASTERN_TIMEZONE)
        
        # Weekday summarizer hours (8:25am-5:25pm ET)
        if now_eastern.weekday() < 5:  # Monday to Friday
            summarizer_start = now_eastern.replace(hour=8, minute=25, second=0, microsecond=0)
            summarizer_end = now_eastern.replace(hour=17, minute=25, second=0, microsecond=0)
            return summarizer_start <= now_eastern <= summarizer_end
        
        # Weekend summarizer (3pm ET)
        else:
            weekend_time = now_eastern.replace(hour=15, minute=0, second=0, microsecond=0)
            return abs((now_eastern - weekend_time).total_seconds()) < 300  # Within 5 minutes of 3pm
    
    def is_decider_time(self):
        """
        Check if it's time to run decider.
        Decider ALWAYS runs when summaries are available (even after hours).
        Market hours check happens during execution - decisions are marked as 'MARKET CLOSED' if after hours.
        """
        return True  # Always run decider to analyze summaries and record decisions
    
    def is_feedback_time(self):
        """Check if it's time to run feedback (weekly: Thursday night, post-close)."""
        now_local = datetime.now(LOCAL_TIMEZONE)
        now_eastern = now_local.astimezone(EASTERN_TIMEZONE)
        
        # Weekly cadence: Thursday nights after close
        if now_eastern.weekday() != 3:  # 0=Mon, 3=Thu
            return False
        
        feedback_start = now_eastern.replace(hour=20, minute=0, second=0, microsecond=0)  # 8:00 PM ET
        feedback_end = now_eastern.replace(hour=23, minute=30, second=0, microsecond=0)   # 11:30 PM ET
        
        # Skip if already ran today
        if self._feedback_already_ran_today():
            return False
        
        return feedback_start <= now_eastern <= feedback_end
    
    def _feedback_already_ran_today(self):
        """Check if feedback agent already ran today for this configuration"""
        try:
            from config import engine, get_current_config_hash
            from sqlalchemy import text
            
            config_hash = get_current_config_hash()
            
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT COUNT(*) as count
                    FROM system_runs 
                    WHERE run_type = 'feedback' 
                    AND start_time >= CURRENT_DATE
                    AND status = 'completed'
                    AND details->>'config_hash' = :config_hash
                """), {"config_hash": config_hash}).fetchone()
                
                return result.count > 0
        except Exception as e:
            logger.warning(f"Could not check if feedback ran today: {e}")
            return False  # If we can't check, allow it to run
    
    def get_unprocessed_summaries(self):
        """Get all summaries that haven't been processed by the decider yet"""
        from config import get_current_config_hash
        config_hash = get_current_config_hash()
        
        with engine.connect() as conn:
            # Get all summaries that haven't been processed (filtered by config_hash)
            result = conn.execute(text("""
                SELECT s.id, s.agent, s.timestamp, s.run_id, s.data
                FROM summaries s
                LEFT JOIN processed_summaries ps ON s.id = ps.summary_id AND ps.processed_by = 'decider'
                WHERE ps.summary_id IS NULL AND s.config_hash = :config_hash
                ORDER BY s.timestamp ASC
            """), {"config_hash": config_hash})
            return [row._mapping for row in result]
    
    def get_recent_summaries(self, hours_back=6):
        """Get summaries from the latest run (processed or not)"""
        from config import get_current_config_hash
        config_hash = get_current_config_hash()
        
        with engine.connect() as conn:
            # First, get the latest run_id
            latest_run_result = conn.execute(text("""
                SELECT run_id 
                FROM summaries 
                WHERE config_hash = :config_hash
                ORDER BY timestamp DESC 
                LIMIT 1
            """), {"config_hash": config_hash})
            
            latest_run_row = latest_run_result.fetchone()
            if not latest_run_row:
                return []
            
            latest_run_id = latest_run_row.run_id
            
            # Get all summaries from the latest run
            result = conn.execute(text("""
                SELECT s.id, s.agent, s.timestamp, s.run_id, s.data
                FROM summaries s
                WHERE s.run_id = :run_id
                  AND s.config_hash = :config_hash
                ORDER BY s.timestamp DESC
            """), {"run_id": latest_run_id, "config_hash": config_hash})
            return [row._mapping for row in result]
    
    def mark_summaries_processed(self, summary_ids, processed_by):
        """Mark summaries as processed"""
        with engine.begin() as conn:
            for summary_id in summary_ids:
                conn.execute(text("""
                    INSERT INTO processed_summaries (summary_id, processed_by, run_id)
                    VALUES (:summary_id, :processed_by, :run_id)
                """), {
                    "summary_id": summary_id,
                    "processed_by": processed_by,
                    "run_id": datetime.now().strftime("%Y%m%dT%H%M%S")
                })
    
    def run_summarizer_agents(self):
        """Run the summarizer agents"""
        # Create both the internal run_id and the timestamp for main.py
        internal_run_id = f"summarizer_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        timestamp = datetime.now().strftime('%Y%m%dT%H%M%S')
        logger.info(f"Starting summarizer agents run: {internal_run_id}")
        
        try:
            # Record run start
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO system_runs (run_type, details)
                    VALUES ('summarizer', :details)
                """), {
                    "details": json.dumps({"run_id": internal_run_id, "timestamp": datetime.now().isoformat()})
                })
            
            # Run the summarizer agents with the correct timestamp format
            summarizer_main.RUN_TIMESTAMP = timestamp
            summarizer_main.RUN_DIR = os.path.join(summarizer_main.SCREENSHOT_DIR, timestamp)
            os.makedirs(summarizer_main.RUN_DIR, exist_ok=True)
            summarizer_main.run_summary_agents()
            
            logger.info(f"Summarizer agents completed successfully: {internal_run_id}")
            
            # Update run status
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE system_runs 
                    SET end_time = CURRENT_TIMESTAMP, status = 'completed'
                    WHERE run_type = 'summarizer' AND details->>'run_id' = :run_id
                """), {"run_id": internal_run_id})
                
        except Exception as e:
            logger.error(f"Error running summarizer agents: {e}")
            # Update run status to failed
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE system_runs 
                    SET end_time = CURRENT_TIMESTAMP, status = 'failed'
                    WHERE run_type = 'summarizer' AND details->>'run_id' = :run_id
                """), {"run_id": internal_run_id})
    
    def run_decider_agent(self, force=False):
        """
        Run the decider agent with all unprocessed summaries.
        
        Args:
            force: If True, indicates the call is part of an orchestrated cycle (startup, scheduled,
                market-open, etc.). Currently this flag is informational.
        
        Returns:
            bool: True if the decider executed successfully, False if it failed early.
        """
        run_id = f"decider_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        logger.info(f"Starting decider agent run: {run_id}")
        
        try:
            if get_trading_mode().lower() == "real_world":
                logger.info("🔁 Syncing live Schwab portfolio before decider run")
                try:
                    sync_result = trading_interface.sync_schwab_positions(persist=True)
                    if sync_result.get("status") != "success":
                        logger.warning("⚠️  Schwab sync prior to decider returned %s", sync_result.get("message") or sync_result.get("error"))
                    else:
                        logger.info("✅ Live Schwab portfolio synchronized")
                except Exception as sync_exc:
                    logger.error("⚠️  Schwab sync failed before decider run: %s", sync_exc)

            # Record run start
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO system_runs (run_type, details)
                    VALUES ('decider', :details)
                """), {
                    "details": json.dumps({"run_id": run_id, "timestamp": datetime.now().isoformat()})
                })
            
            # Get unprocessed summaries
            unprocessed_summaries = self.get_unprocessed_summaries()
            
            if not unprocessed_summaries:
                logger.info("No unprocessed summaries found for decider - using latest run summaries")
                # Get summaries from the latest run instead of empty list
                unprocessed_summaries = self.get_recent_summaries()
                if unprocessed_summaries:
                    latest_run_id = unprocessed_summaries[0]['run_id']
                    logger.info(f"Using {len(unprocessed_summaries)} summaries from latest run {latest_run_id}")
                else:
                    logger.info("No summaries available - will record market status only")
                    unprocessed_summaries = []
            else:
                logger.info(f"Found {len(unprocessed_summaries)} unprocessed summaries")
            
            # Determine which summarizer run to process
            target_run_id = None
            summaries_to_process = unprocessed_summaries
            if unprocessed_summaries:
                run_id_candidates = []
                for summary in unprocessed_summaries:
                    summary_run_id = summary.get('run_id')
                    summary_timestamp = summary.get('timestamp')
                    if summary_run_id:
                        run_id_candidates.append((summary_timestamp, summary_run_id))
                if run_id_candidates:
                    # Sort by timestamp, defaulting missing timestamps to minimal value
                    run_id_candidates.sort(key=lambda item: item[0] or datetime.min)
                    target_run_id = run_id_candidates[-1][1]
                    summaries_filtered = [s for s in unprocessed_summaries if s.get('run_id') == target_run_id]
                    if summaries_filtered:
                        summaries_to_process = summaries_filtered
                        logger.info(f"Processing {len(summaries_filtered)} summaries for run {target_run_id}")
                else:
                    latest_timestamp = max(s.get('timestamp') for s in unprocessed_summaries if s.get('timestamp'))
                    target_run_id = latest_timestamp.strftime("%Y%m%dT%H%M%S") if latest_timestamp else None
            else:
                target_run_id = None

            if not target_run_id:
                # Fallback when no run_id metadata exists
                target_run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
                logger.info(f"No summarizer run_id detected; using fallback decider run id {target_run_id}")

            # Temporarily override the get_latest_run_id function
            original_get_latest_run_id = decider.get_latest_run_id
            
            def mock_get_latest_run_id():
                return target_run_id
            
            decider.get_latest_run_id = mock_get_latest_run_id
            
            # Update current prices before making decisions
            decider.update_all_current_prices()
            
            # Run the decider agent
            summaries = summaries_to_process
            holdings = decider.fetch_holdings()
            
            try:
                decisions = decider.ask_decision_agent(summaries, target_run_id, holdings)
                logger.info(f"✅ Decider AI returned {len(decisions) if isinstance(decisions, list) else 1} decisions")
            except Exception as e:
                logger.error(f"❌ Decider AI call failed: {e}")
                import traceback
                logger.error(f"Traceback:\n{traceback.format_exc()}")
                # Use empty decisions list if AI fails
                decisions = []
            
            if decisions:
                validated_decisions = decider.store_trade_decisions(decisions, target_run_id)
                if validated_decisions:
                    decider.update_holdings(validated_decisions)
                else:
                    logger.warning("⚠️  All decisions were rejected; nothing to execute.")
                decider.record_portfolio_snapshot()
            else:
                logger.warning("⚠️  No decisions to process - AI returned empty or failed")
            
            # Mark summaries as processed
            summary_ids = [s['id'] for s in summaries]
            self.mark_summaries_processed(summary_ids, 'decider')
            
            # Restore original function
            decider.get_latest_run_id = original_get_latest_run_id
            
            logger.info(f"Decider agent completed successfully: {run_id}")
            
            # Update run status
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE system_runs 
                    SET end_time = CURRENT_TIMESTAMP, status = 'completed'
                    WHERE run_type = 'decider' AND details->>'run_id' = :run_id
                """), {"run_id": run_id})
            return True
                
        except Exception as e:
            logger.error(f"Error running decider agent: {e}")
            import traceback
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            # Update run status to failed
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE system_runs 
                    SET end_time = CURRENT_TIMESTAMP, status = 'failed'
                    WHERE run_type = 'decider' AND details->>'run_id' = :run_id
                """), {"run_id": run_id})
            return False
    
    def run_feedback_agent(self):
        """Run the feedback agent for daily analysis across all active config hashes"""
        run_id = f"feedback_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        logger.info(f"Starting feedback agent run for all configs: {run_id}")
        
        # PRESERVE the original configuration hash set during startup
        from config import get_current_config_hash
        original_config_hash = get_current_config_hash()
        logger.info(f"Original configuration hash: {original_config_hash}")
        
        # Get all config hashes that have had recent trading activity
        active_configs = self._get_active_config_hashes()
        
        if not active_configs:
            logger.info("No active config hashes found - skipping feedback")
            return
            
        logger.info(f"Found {len(active_configs)} active config hashes: {active_configs}")
        
        for config_hash in active_configs:
            try:
                logger.info(f"Running feedback analysis for config {config_hash}")
                
                # Record run start for this config
                with engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO system_runs (run_type, details)
                        VALUES ('feedback', :details)
                    """), {
                        "details": json.dumps({
                            "run_id": f"{run_id}_{config_hash[:8]}", 
                            "timestamp": datetime.now().isoformat(),
                            "config_hash": config_hash
                        })
                    })
                
                # Run the feedback analysis for this specific config
                # WITHOUT changing the global configuration hash
                feedback_tracker = TradeOutcomeTracker()
                result = feedback_tracker.analyze_recent_outcomes_for_config(config_hash)
                
                if result:
                    logger.info(f"Feedback analysis completed for config {config_hash}")
                else:
                    logger.info(f"No feedback analysis needed for config {config_hash}")
                
                # Update run status to completed
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE system_runs 
                        SET end_time = CURRENT_TIMESTAMP, status = 'completed'
                        WHERE run_type = 'feedback' AND details->>'run_id' = :run_id
                    """), {"run_id": f"{run_id}_{config_hash[:8]}"})
                    
            except Exception as e:
                logger.error(f"Error running feedback for config {config_hash}: {e}")
                # Update run status to failed
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE system_runs 
                        SET end_time = CURRENT_TIMESTAMP, status = 'failed'
                        WHERE run_type = 'feedback' AND details->>'run_id' = :run_id
                    """), {"run_id": f"{run_id}_{config_hash[:8]}"})
        
        # RESTORE the original configuration hash
        os.environ['CURRENT_CONFIG_HASH'] = original_config_hash
        logger.info(f"Restored original configuration hash: {original_config_hash}")
        logger.info(f"Feedback agent run completed for all configs: {run_id}")
    
    def _get_active_config_hashes(self):
        """Get config hashes that have had recent activity (decisions OR summaries)"""
        try:
            with engine.connect() as conn:
                # Get config hashes that have had ANY activity in the last 2 days
                # This includes trade decisions, summaries, or just being actively used
                result = conn.execute(text("""
                    SELECT DISTINCT config_hash
                    FROM (
                        -- Configs with trade decisions
                        SELECT config_hash FROM trade_decisions 
                        WHERE timestamp >= NOW() - INTERVAL '2 days' AND config_hash IS NOT NULL
                        
                        UNION
                        
                        -- Configs with recent summaries (shows active usage)
                        SELECT config_hash FROM summaries 
                        WHERE timestamp >= NOW() - INTERVAL '2 days' AND config_hash IS NOT NULL
                        
                        UNION
                        
                        -- Configs that were recently used (from run_configurations)
                        SELECT config_hash FROM run_configurations 
                        WHERE last_used >= NOW() - INTERVAL '2 days'
                    ) AS active_configs
                    ORDER BY config_hash
                """))
                
                return [row.config_hash for row in result]
        except Exception as e:
            logger.error(f"Error getting active config hashes: {e}")
            return []
    
    def scheduled_summarizer_job(self):
        """Scheduled job for summarizer agents"""
        try:
            if self.is_summarizer_time():
                logger.info("Running scheduled summarizer job")
                self.run_summarizer_agents()
                logger.info("✅ Scheduled summarizer job completed successfully")
            else:
                logger.info("Skipping summarizer job - outside of scheduled time")
        except Exception as e:
            logger.error(f"❌ Scheduled summarizer job failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def scheduled_decider_job(self):
        """
        Scheduled job for decider agent.
        Decider ALWAYS runs to analyze summaries and record decisions.
        Market hours check happens during execution to prevent actual trading after hours.
        """
        try:
            logger.info("Running scheduled decider job (will mark as 'MARKET CLOSED' if after hours)")
            executed = self.run_decider_agent(force=True)
            if executed:
                logger.info("✅ Scheduled decider job completed successfully")
            else:
                logger.warning("⚠️  Scheduled decider job failed earlier in the log output.")
        except Exception as e:
            logger.error(f"❌ Scheduled decider job failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def scheduled_feedback_job(self):
        """Scheduled job for feedback agent"""
        try:
            if self.is_feedback_time():
                logger.info("Running scheduled feedback job")
                self.run_feedback_agent()
                logger.info("✅ Scheduled feedback job completed successfully")
            else:
                logger.info("Skipping feedback job - outside of scheduled time")
        except Exception as e:
            logger.error(f"❌ Scheduled feedback job failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def scheduled_summarizer_and_decider_job(self):
        """Sequential job: Run summarizers first, then decider with collected summaries"""
        try:
            now_eastern = datetime.now(LOCAL_TIMEZONE).astimezone(EASTERN_TIMEZONE)
            market_open_et = now_eastern.replace(hour=9, minute=30, second=0, microsecond=0)
            if now_eastern.date() != self._startup_date_et and now_eastern < market_open_et:
                logger.info("⏳ Skipping scheduled cycle before market open on non-startup day.")
                return
            remaining_seconds = manual_decider_skip_seconds()
            if remaining_seconds > 0:
                remaining_minutes = max(0.1, remaining_seconds / 60.0)
                logger.info(
                    "⏳ Manual decider cooldown active (%.1f minutes remain) — proceeding anyway to keep scheduled cycle atomic.",
                    remaining_minutes
                )
            # Step 1: Run summarizers (always when scheduled)
            if self.is_summarizer_time():
                logger.info("🔄 Step 1: Running summarizer agents")
                self.run_summarizer_agents()
                logger.info("✅ Step 1 completed: Summarizer agents finished")
                
                # Step 2: Run decider after summaries (market check happens during execution).
                logger.info("🔄 Step 2: Running decider agent with fresh summaries")
                executed = self.run_decider_agent(force=True)
                if executed:
                    logger.info("✅ Step 2 completed: Decider agent finished (decisions marked if market closed)")
                else:
                    logger.warning("⚠️  Step 2 failed (see earlier logs for details).")
                
                logger.info("✅ Sequential job completed successfully")
            else:
                logger.info("Skipping job - outside of summarizer time")
                
        except Exception as e:
            logger.error(f"❌ Sequential job failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def market_open_job(self):
        """
        Special job that runs at market open (9:30:05 AM ET).
        Runs summarizers at 9:30 AM ET, then waits until exactly 9:30:05 AM ET to execute trades.
        """
        try:
            now_local = datetime.now(LOCAL_TIMEZONE)
            now_eastern = now_local.astimezone(EASTERN_TIMEZONE)
            today_et = now_eastern.date()
            
            # Only run on weekdays
            if now_eastern.weekday() >= 5:
                logger.info("Skipping market open job - weekend")
                return
            
            if self._market_open_run_date == today_et:
                logger.info("Market open job already executed today; skipping duplicate trigger.")
                return
            
            logger.info("🔔 MARKET OPEN SEQUENCE STARTING")
            logger.info(f"   Current time: {now_eastern.strftime('%I:%M:%S %p ET')}")
            
            # Step 1: Run summarizers right at the bell (9:30 AM ET)
            logger.info("📰 Step 1: Market-open news analysis (9:30 AM ET)")
            self.run_summarizer_agents()
            logger.info("✅ Market-open analysis complete")
            
            # Step 2: Wait until exactly 9:30:05 AM ET
            now_eastern = datetime.now(LOCAL_TIMEZONE).astimezone(EASTERN_TIMEZONE)
            market_open_time = now_eastern.replace(hour=9, minute=30, second=5, microsecond=0)
            
            if now_eastern < market_open_time:
                wait_seconds = (market_open_time - now_eastern).total_seconds()
                logger.info(f"⏰ Waiting {wait_seconds:.0f} seconds until market opens at 9:30:05 AM ET...")
                time.sleep(wait_seconds)
            
            # Step 3: Execute trades at market open
            now_eastern = datetime.now(LOCAL_TIMEZONE).astimezone(EASTERN_TIMEZONE)
            logger.info(f"🚀 EXECUTING OPENING TRADES at {now_eastern.strftime('%I:%M:%S %p ET')}")
            executed = self.run_decider_agent(force=True)
            if executed:
                logger.info("✅ Opening trades executed!")
            else:
                logger.warning("⚠️  Opening decider run failed (see earlier logs for details).")
            self._market_open_run_date = today_et
            self._startup_cycle_completed = True
            
        except Exception as e:
            logger.error(f"❌ Market open job failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _run_market_open_catchup_if_needed(self):
        """If the orchestrator starts after 9:30 ET, immediately run the market-open sequence once."""
        now_eastern = datetime.now(EASTERN_TIMEZONE)
        if now_eastern.weekday() >= 5:
            return
        market_open_et = now_eastern.replace(hour=9, minute=30, second=0, microsecond=0)
        if now_eastern >= market_open_et and self._market_open_run_date != now_eastern.date():
            logger.warning("⚠️  Market open time already passed today; running catch-up opening sequence now.")
            self.market_open_job()

    def _summarizer_ran_today(self):
        """Return True if a summarizer run was recorded today (any process)."""
        try:
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT COUNT(*) AS count
                    FROM system_runs
                    WHERE run_type = 'summarizer'
                      AND start_time >= CURRENT_DATE
                """)).fetchone()
                return (result and result.count and int(result.count) > 0)
        except Exception as exc:
            logger.warning(f"Unable to check summarizer runs today: {exc}")
            return False

    def _ensure_cadence_anchor(self):
        """Set or reset the next cadence run time based on day and cadence rules."""
        now_et = datetime.now(EASTERN_TIMEZONE)
        # Switch anchor depending on whether it's the startup day
        if now_et.date() == self._startup_time_et.date():
            anchor = self._startup_time_et + timedelta(minutes=self._cadence_minutes)
        else:
            market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
            anchor = market_open + timedelta(minutes=self._cadence_minutes)
        if self._next_cadence_run_et is None or self._next_cadence_run_et.date() != now_et.date():
            self._next_cadence_run_et = anchor
        elif self._next_cadence_run_et < anchor:
            self._next_cadence_run_et = anchor

    def cadence_tick(self):
        """Run cadence-aligned summarizer/decider cycles."""
        self._ensure_cadence_anchor()
        if self._next_cadence_run_et is None:
            return
        now_et = datetime.now(EASTERN_TIMEZONE)
        if now_et < self._next_cadence_run_et:
            return
        # Run once per tick; if more than one cadence interval elapsed, catch up one interval at a time
        while self._next_cadence_run_et and now_et >= self._next_cadence_run_et:
            logger.info(f"⏰ Cadence trigger at {now_et.strftime('%H:%M:%S ET')} (next run target was {self._next_cadence_run_et.strftime('%H:%M ET')})")
            self.scheduled_summarizer_and_decider_job()
            self._next_cadence_run_et += timedelta(minutes=self._cadence_minutes)
    
    def setup_schedule(self):
        """Setup the scheduling for all jobs with configurable cadence"""
        def _et_to_local_time_str(et_hhmm: str) -> str:
            """Convert an ET HH:MM string to local-time HH:MM for the scheduler."""
            try:
                hour, minute = map(int, et_hhmm.split(":"))
                now_et = datetime.now(EASTERN_TIMEZONE)
                target_et = now_et.replace(hour=hour, minute=minute, second=0, microsecond=0)
                target_local = target_et.astimezone(LOCAL_TIMEZONE)
                return target_local.strftime("%H:%M")
            except Exception as exc:
                logger.warning(f"Failed to convert ET time '{et_hhmm}' to local; defaulting to same string. Error: {exc}")
                return et_hhmm

        # Get cadence from environment (default: 180 minutes = 3 hours)
        cadence_minutes = self._cadence_minutes
        
        # SPECIAL: Market open job at 9:30 AM ET (runs at the bell)
        market_open_local = _et_to_local_time_str("09:30")  # e.g., 06:30 PT
        schedule.every().day.at(market_open_local).do(self.market_open_job)
        
        # Regular cadence: we drive via cadence_tick every minute (aligned to startup day or market open on subsequent days)
        schedule.every(1).minutes.do(self.cadence_tick)
        
        # Feedback agent - weekly, Thursday nights after market close (8:30 PM ET / 5:30 PM PT)
        weekly_feedback_local = _et_to_local_time_str("20:30")  # e.g., 17:30 PT
        schedule.every().thursday.at(weekly_feedback_local).do(self.scheduled_feedback_job)
        
        logger.info("="*60)
        logger.info("Schedule setup completed")
        logger.info(f"📊 DAY TRADING MODE:")
        logger.info(f"   🔔 Market Open (9:30:05 AM ET):")
        logger.info(f"      - {market_open_local} {LOCAL_TZ_ABBR} / 9:30:00 ET: Analyze news at the bell")
        logger.info(f"      - 9:30:05 AM ET: Execute opening trades (5 sec after bell)")
        logger.info(f"   📈 Regular Cadence:")
        logger.info(f"      - Day 1 anchor: startup time + cadence")
        logger.info(f"      - Subsequent days: first cadence run at 9:30 AM ET + cadence, then every {cadence_minutes} minutes")
        logger.info(f"   📊 Feedback: Weekly on Thursday at 8:30 PM ET ({weekly_feedback_local} {LOCAL_TZ_ABBR})")
        if cadence_minutes <= 15:
            # 390 minutes of trading (9:30 AM - 4:00 PM) minus opening trade
            cycles = int(390 / cadence_minutes)
            logger.info(f"   ⚡ AGGRESSIVE: Up to {cycles + 1} trading cycles per day!")
        logger.info("="*60)
        self._run_market_open_catchup_if_needed()
    
    def run(self):
        """Main run loop"""
        logger.info("Starting D-AI-Trader automation system")
        self.setup_schedule()
        
        # Get cadence for display
        cadence_minutes = self._cadence_minutes
        
        skip_cycle = os.getenv("DAI_SKIP_STARTUP_CYCLE", "0").lower() in {"1", "true", "yes"}
        now_et = datetime.now(EASTERN_TIMEZONE)
        market_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if skip_cycle:
            logger.info("⏸️  Startup cycle skipped (DAI_SKIP_STARTUP_CYCLE is set).")
        elif self._startup_cycle_completed:
            logger.info("⚡ Startup cycle already satisfied via market-open catch-up; skipping immediate run.")
        elif now_et < market_open_et and self._summarizer_ran_today():
            logger.info("⏳ Startup before market open; summarizer already ran today. Waiting for 9:30 AM ET scheduled market-open run.")
        else:
            try:
                if self.is_summarizer_time():
                    logger.info("⚡ Startup inside trading window – running immediate summarizer + decider cycle.")
                else:
                    logger.info("⚡ Startup outside preferred window – forcing immediate summarizer + decider cycle.")
                self.run_summarizer_agents()
                logger.info("✅ Startup summarizer run complete.")
                executed = self.run_decider_agent(force=True)
                if executed:
                    logger.info("✅ Startup decider run complete.")
                else:
                    logger.warning("⚠️  Startup decider run failed (see earlier logs for details).")
                # Anchor cadence after the startup run to avoid double-running immediately
                self._next_cadence_run_et = self._startup_time_et + timedelta(minutes=self._cadence_minutes)
            except Exception as exc:
                logger.error(f"❌ Startup cycle failed: {exc}")
                import traceback
                logger.error(traceback.format_exc())

        logger.info("")
        logger.info("="*60)
        logger.info("📅 DAY TRADING SYSTEM ACTIVE")
        logger.info("="*60)
        logger.info("")
        logger.info("🔔 OPENING BELL STRATEGY (Every Trading Day):")
        logger.info("   9:30:00 AM ET (6:30 AM PT) - Analyze news at the bell")
        logger.info("   9:30:05 AM ET (6:30 AM PT) - Execute opening trades (5 sec after bell)")
        logger.info("")
        logger.info(f"📈 INTRADAY TRADING CYCLE:")
        logger.info(f"   Every {cadence_minutes} minutes from 9:35 AM - 4:00 PM ET")
        if cadence_minutes <= 15:
            cycles_per_day = int(390 / cadence_minutes) + 1  # +1 for opening bell
            logger.info(f"   ⚡ AGGRESSIVE MODE: Up to {cycles_per_day} trades/day!")
        logger.info("")
        logger.info("📊 END OF DAY:")
        logger.info("   4:30 PM ET - Performance feedback & strategy refinement")
        logger.info("")
        logger.info("⛔ AFTER HOURS:")
        logger.info("   Decisions recorded but marked 'MARKET CLOSED' (no execution)")
        logger.info("")
        logger.info("="*60)
        logger.info("🕐 System initialized. Waiting for next scheduled run...")
        logger.info("="*60)
        logger.info("")
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
                
        except KeyboardInterrupt:
            logger.info("Shutting down D-AI-Trader automation system")
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            raise

def main():
    """Main entry point"""
    orchestrator = DAITraderOrchestrator()
    orchestrator.run()

if __name__ == "__main__":
    main() 
