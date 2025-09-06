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
from datetime import datetime, timedelta
import pytz
from sqlalchemy import text
from config import engine, PromptManager, session, openai
from feedback_agent import TradeOutcomeTracker

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
PACIFIC_TIMEZONE = pytz.timezone('US/Pacific')
EASTERN_TIMEZONE = pytz.timezone('US/Eastern')

# Market hours configuration (Eastern Time - market hours are always ET)
MARKET_OPEN_TIME = "09:30"
MARKET_CLOSE_TIME = "16:00"
SUMMARIZER_START_TIME = "08:25"
SUMMARIZER_END_TIME = "17:25"
WEEKEND_SUMMARIZER_TIME = "15:00"  # 3pm ET

class DAITraderOrchestrator:
    def __init__(self):
        self.prompt_manager = PromptManager(client=openai, session=session)
        self.last_processed_summary_id = None
        self.initialize_database()
        
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
        # Get current time in Pacific, convert to Eastern for market hours check
        now_pacific = datetime.now(PACIFIC_TIMEZONE)
        now_eastern = now_pacific.astimezone(EASTERN_TIMEZONE)
        
        # Check if it's a weekday (Monday = 0, Sunday = 6)
        if now_eastern.weekday() >= 5:  # Saturday or Sunday
            return False
            
        # Check if it's within market hours (Eastern Time)
        market_open = now_eastern.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_eastern.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= now_eastern <= market_close
    
    def is_summarizer_time(self):
        """Check if it's time to run summarizers"""
        # Get current time in Pacific, convert to Eastern for time checks
        now_pacific = datetime.now(PACIFIC_TIMEZONE)
        now_eastern = now_pacific.astimezone(EASTERN_TIMEZONE)
        
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
        """Check if it's time to run decider (market hours only)"""
        return self.is_market_open()
    
    def is_feedback_time(self):
        """Check if it's time to run feedback (after market close)"""
        # Get current time in Pacific, convert to Eastern for time checks
        now_pacific = datetime.now(PACIFIC_TIMEZONE)
        now_eastern = now_pacific.astimezone(EASTERN_TIMEZONE)
        
        # Only on weekdays
        if now_eastern.weekday() >= 5:
            return False
            
        # After market close (4pm ET) but before 6pm ET to ensure it runs daily
        market_close = now_eastern.replace(hour=16, minute=0, second=0, microsecond=0)
        feedback_window_end = now_eastern.replace(hour=18, minute=0, second=0, microsecond=0)
        
        # Check if feedback already ran today
        if self._feedback_already_ran_today():
            return False
            
        return market_close <= now_eastern <= feedback_window_end
    
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
    
    def run_decider_agent(self):
        """Run the decider agent with all unprocessed summaries"""
        run_id = f"decider_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        logger.info(f"Starting decider agent run: {run_id}")
        
        try:
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
            
            # Create a mock run_id for the decider to use
            # We'll use the latest timestamp from the summaries, or current time if no summaries
            if unprocessed_summaries:
                latest_timestamp = max(s['timestamp'] for s in unprocessed_summaries)
                mock_run_id = latest_timestamp.strftime("%Y%m%dT%H%M%S")
            else:
                # No summaries, use current time for run_id
                mock_run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
            
            # Temporarily override the get_latest_run_id function
            original_get_latest_run_id = decider.get_latest_run_id
            
            def mock_get_latest_run_id():
                return mock_run_id
            
            decider.get_latest_run_id = mock_get_latest_run_id
            
            # Update current prices before making decisions
            decider.update_all_current_prices()
            
            # Run the decider agent
            summaries = unprocessed_summaries
            holdings = decider.fetch_holdings()
            decisions = decider.ask_decision_agent(summaries, mock_run_id, holdings)
            decider.store_trade_decisions(decisions, mock_run_id)
            decider.update_holdings(decisions)
            decider.record_portfolio_snapshot()
            
            # Mark summaries as processed
            summary_ids = [s['id'] for s in unprocessed_summaries]
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
                
        except Exception as e:
            logger.error(f"Error running decider agent: {e}")
            # Update run status to failed
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE system_runs 
                    SET end_time = CURRENT_TIMESTAMP, status = 'failed'
                    WHERE run_type = 'decider' AND details->>'run_id' = :run_id
                """), {"run_id": run_id})
    
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
        """Scheduled job for decider agent"""
        try:
            if self.is_decider_time():
                logger.info("Running scheduled decider job")
                self.run_decider_agent()
                logger.info("✅ Scheduled decider job completed successfully")
            else:
                logger.info("Skipping decider job - market is closed")
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
            # Step 1: Run summarizers (always when scheduled)
            if self.is_summarizer_time():
                logger.info("🔄 Step 1: Running summarizer agents")
                self.run_summarizer_agents()
                logger.info("✅ Step 1 completed: Summarizer agents finished")
                
                # Step 2: Run decider ONLY during market hours and ONLY after summaries are collected
                if self.is_decider_time():
                    logger.info("🔄 Step 2: Running decider agent with fresh summaries")
                    self.run_decider_agent()
                    logger.info("✅ Step 2 completed: Decider agent finished")
                else:
                    logger.info("⏸️  Step 2 skipped: Market is closed - summaries collected for future decisions")
                
                logger.info("✅ Sequential job completed successfully")
            else:
                logger.info("Skipping job - outside of summarizer time")
                
        except Exception as e:
            logger.error(f"❌ Sequential job failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def setup_schedule(self):
        """Setup the scheduling for all jobs"""
        # Summarizer agents - every hour during market hours and once daily on weekends
        schedule.every().hour.at(":25").do(self.scheduled_summarizer_and_decider_job)  # Every hour at :25
        
        # Feedback agent - once daily after market close
        schedule.every().day.at("16:30").do(self.scheduled_feedback_job)  # 4:30pm ET
        
        logger.info("Schedule setup completed")
        logger.info("Summarizer + Decider: Every hour at :25 (sequential execution)")
        logger.info("Feedback agent: Daily at 4:30pm ET")
    
    def run(self):
        """Main run loop"""
        logger.info("Starting D-AI-Trader automation system")
        self.setup_schedule()
        
        # Skip immediate cycle - rely on scheduled runs only
        logger.info("📅 System will run on schedule:")
        logger.info("  - STEP 1: Summarizer agents collect news (every hour at :25)")  
        logger.info("  - STEP 2: Decider agent analyzes summaries (immediately after Step 1, during market hours only)")
        logger.info("  - STEP 3: Feedback agent (daily at 4:30pm ET)")
        logger.info("🔄 Sequential execution ensures decider uses fresh summaries")
        logger.info("🕐 Waiting for next scheduled run...")
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