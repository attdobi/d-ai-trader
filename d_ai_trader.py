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
    """Simplified orchestrator using unified agent execution framework"""

    def __init__(self):
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
    
    # Database management methods (kept for compatibility)
    def get_unprocessed_summaries(self):
        """Legacy method - now handled by unified executor"""
        from agent_executor import agent_executor
        return agent_executor._get_unprocessed_summaries()

    def mark_summaries_processed(self, summary_ids, processed_by):
        """Legacy method - now handled by unified executor"""
        from agent_executor import agent_executor
        return agent_executor._mark_summaries_processed(summary_ids, processed_by)
    
    def run_summarizer_agents(self):
        """Run the summarizer agents using unified executor"""
        from agent_executor import run_summarizer_agents as unified_summarizer

        run_id = f"summarizer_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        logger.info(f"Starting summarizer agents run: {run_id}")

        result = unified_summarizer(run_id)

        if result.success:
            logger.info(f"Summarizer agents completed successfully: {result.message}")
        else:
            logger.error(f"Summarizer agents failed: {result.message}")
    
    def run_decider_agent(self):
        """Run the decider agent using unified executor"""
        from agent_executor import run_decider_agent as unified_decider

        run_id = f"decider_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        logger.info(f"Starting decider agent run: {run_id}")

        result = unified_decider(run_id)

        if result.success:
            logger.info(f"Decider agent completed successfully: {result.message}")
        else:
            logger.error(f"Decider agent failed: {result.message}")
    
    def run_feedback_agent(self):
        """Run the feedback agent using unified executor"""
        from agent_executor import run_feedback_agent as unified_feedback

        run_id = f"feedback_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        logger.info(f"Starting feedback agent run: {run_id}")

        result = unified_feedback(run_id)

        if result.success:
            logger.info(f"Feedback agent completed successfully: {result.message}")
        else:
            logger.error(f"Feedback agent failed: {result.message}")
    
    # Legacy methods for compatibility (now handled by unified executor)
    def _get_active_config_hashes(self):
        """Legacy method - feedback now handled per configuration"""
        return []
    
    def scheduled_summarizer_job(self):
        """Scheduled job for summarizer agents using unified executor"""
        try:
            if self.is_summarizer_time():
                logger.info("Running scheduled summarizer job")
                from agent_executor import run_summarizer_agents
                result = run_summarizer_agents()
                logger.info(f"✅ Scheduled summarizer job: {'completed' if result.success else 'failed'}")
            else:
                logger.info("Skipping summarizer job - outside of scheduled time")
        except Exception as e:
            logger.error(f"❌ Scheduled summarizer job failed: {e}")

    def scheduled_decider_job(self):
        """Scheduled job for decider agent using unified executor"""
        try:
            if self.is_decider_time():
                logger.info("Running scheduled decider job")
                from agent_executor import run_decider_agent
                result = run_decider_agent()
                logger.info(f"✅ Scheduled decider job: {'completed' if result.success else 'failed'}")
            else:
                logger.info("Skipping decider job - market is closed")
        except Exception as e:
            logger.error(f"❌ Scheduled decider job failed: {e}")

    def scheduled_feedback_job(self):
        """Scheduled job for feedback agent using unified executor"""
        try:
            if self.is_feedback_time():
                logger.info("Running scheduled feedback job")
                from agent_executor import run_feedback_agent
                result = run_feedback_agent()
                logger.info(f"✅ Scheduled feedback job: {'completed' if result.success else 'failed'}")
            else:
                logger.info("Skipping feedback job - outside of scheduled time")
        except Exception as e:
            logger.error(f"❌ Scheduled feedback job failed: {e}")
    
    def scheduled_summarizer_and_decider_job(self):
        """Sequential job: Run summarizers first, then decider with collected summaries"""
        try:
            # Step 1: Run summarizers (always when scheduled)
            if self.is_summarizer_time():
                logger.info("🔄 Step 1: Running summarizer agents")
                from agent_executor import run_summarizer_agents
                summarizer_result = run_summarizer_agents()
                logger.info(f"✅ Step 1: {'completed' if summarizer_result.success else 'failed'}")

                # Step 2: Run decider ONLY during market hours and ONLY after summaries are collected
                if self.is_decider_time():
                    logger.info("🔄 Step 2: Running decider agent with fresh summaries")
                    from agent_executor import run_decider_agent
                    decider_result = run_decider_agent()
                    logger.info(f"✅ Step 2: {'completed' if decider_result.success else 'failed'}")
                else:
                    logger.info("⏸️  Step 2 skipped: Market is closed - summaries collected for future decisions")

                logger.info("✅ Sequential job completed successfully")
            else:
                logger.info("Skipping job - outside of summarizer time")

        except Exception as e:
            logger.error(f"❌ Sequential job failed: {e}")
    
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