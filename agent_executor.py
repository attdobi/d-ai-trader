#!/usr/bin/env python3
"""
Unified Agent Execution Framework
Provides a clean interface for running agents manually or automatically
"""

import os
import json
import time
from datetime import datetime
from sqlalchemy import text
from config import engine, get_current_config_hash, config_manager
from typing import Dict, List, Optional, Any
from error_handler import error_handler, ErrorBoundary

# Setup logging
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AgentExecutionResult:
    """Result of an agent execution"""

    def __init__(self, agent_type: str, success: bool, message: str, data: Optional[Dict] = None):
        self.agent_type = agent_type
        self.success = success
        self.message = message
        self.data = data or {}
        self.timestamp = datetime.now()
        self.execution_id = f"{agent_type}_{self.timestamp.strftime('%Y%m%dT%H%M%S')}"

class UnifiedAgentExecutor:
    """Unified executor for all agent types"""

    def __init__(self):
        self.config_hash = get_current_config_hash()

    def execute_summarizer_agents(self, run_id: Optional[str] = None) -> AgentExecutionResult:
        """Execute summarizer agents"""
        try:
            import main as summarizer_main

            # Generate run ID if not provided
            if not run_id:
                run_id = f"summarizer_{datetime.now().strftime('%Y%m%dT%H%M%S')}"

            error_handler.log_info(f"Starting summarizer agents run: {run_id}", "summarizer_agents")

            # Record run start
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO system_runs (run_type, details)
                    VALUES ('summarizer', :details)
                """), {
                    "details": json.dumps({"run_id": run_id, "timestamp": datetime.now().isoformat()})
                })

            # Execute summarizer agents
            summarizer_main.RUN_TIMESTAMP = run_id.split('_')[1] if '_' in run_id else run_id
            summarizer_main.RUN_DIR = os.path.join(summarizer_main.SCREENSHOT_DIR,
                                                 self.config_hash,
                                                 summarizer_main.RUN_TIMESTAMP)
            os.makedirs(summarizer_main.RUN_DIR, exist_ok=True)
            summarizer_main.run_summary_agents()

            # Record success
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE system_runs
                    SET end_time = CURRENT_TIMESTAMP, status = 'completed'
                    WHERE run_type = 'summarizer' AND details->>'run_id' = :run_id
                """), {"run_id": run_id})

            logger.info(f"Summarizer agents completed successfully: {run_id}")
            return AgentExecutionResult("summarizer", True, f"Summarizer agents completed: {run_id}")

        except Exception as e:
            logger.error(f"Error executing summarizer agents: {e}")

            # Record failure
            try:
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE system_runs
                        SET end_time = CURRENT_TIMESTAMP, status = 'failed'
                        WHERE run_type = 'summarizer' AND details->>'run_id' = :run_id
                    """), {"run_id": run_id or "unknown"})
            except:
                pass

            return AgentExecutionResult("summarizer", False, f"Summarizer agents failed: {str(e)}")

    def execute_decider_agent(self, run_id: Optional[str] = None) -> AgentExecutionResult:
        """Execute decider agent"""
        try:
            import decider_agent as decider

            # Generate run ID if not provided
            if not run_id:
                run_id = f"decider_{datetime.now().strftime('%Y%m%dT%H%M%S')}"

            logger.info(f"Starting decider agent run: {run_id}")

            # Record run start
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO system_runs (run_type, details)
                    VALUES ('decider', :details)
                """), {
                    "details": json.dumps({"run_id": run_id, "timestamp": datetime.now().isoformat()})
                })

            # Get unprocessed summaries
            unprocessed_summaries = self._get_unprocessed_summaries()

            if not unprocessed_summaries:
                logger.info("No unprocessed summaries found for decider")
                # Record as completed with no work
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE system_runs
                        SET end_time = CURRENT_TIMESTAMP, status = 'completed'
                        WHERE run_type = 'decider' AND details->>'run_id' = :run_id
                    """), {"run_id": run_id})

                return AgentExecutionResult("decider", True, "No unprocessed summaries found")

            logger.info(f"Found {len(unprocessed_summaries)} unprocessed summaries")

            # Execute decider agent
            summary_ids = [s['id'] for s in unprocessed_summaries]

            # Temporarily override functions for compatibility
            original_get_latest_run_id = decider.get_latest_run_id
            decider.get_latest_run_id = lambda: run_id.split('_')[1] if '_' in run_id else run_id

            # Update prices and execute decisions
            decider.update_all_current_prices()
            holdings = decider.fetch_holdings()
            decisions = decider.ask_decision_agent(unprocessed_summaries, run_id.split('_')[1] if '_' in run_id else run_id, holdings)
            decider.store_trade_decisions(decisions, run_id.split('_')[1] if '_' in run_id else run_id)
            decider.update_holdings(decisions)
            decider.record_portfolio_snapshot()

            # Mark summaries as processed
            self._mark_summaries_processed(summary_ids, 'decider')

            # Restore original function
            decider.get_latest_run_id = original_get_latest_run_id

            # Record success
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE system_runs
                    SET end_time = CURRENT_TIMESTAMP, status = 'completed'
                    WHERE run_type = 'decider' AND details->>'run_id' = :run_id
                """), {"run_id": run_id})

            logger.info(f"Decider agent completed successfully: {run_id}")
            return AgentExecutionResult("decider", True, f"Decider agent completed: {run_id}",
                                      {"decisions_made": len(decisions), "summaries_processed": len(unprocessed_summaries)})

        except Exception as e:
            logger.error(f"Error executing decider agent: {e}")

            # Record failure
            try:
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE system_runs
                        SET end_time = CURRENT_TIMESTAMP, status = 'failed'
                        WHERE run_type = 'decider' AND details->>'run_id' = :run_id
                    """), {"run_id": run_id or "unknown"})
            except:
                pass

            return AgentExecutionResult("decider", False, f"Decider agent failed: {str(e)}")

    def execute_feedback_agent(self, run_id: Optional[str] = None) -> AgentExecutionResult:
        """Execute feedback agent"""
        try:
            from feedback_agent import TradeOutcomeTracker

            # Generate run ID if not provided
            if not run_id:
                run_id = f"feedback_{datetime.now().strftime('%Y%m%dT%H%M%S')}"

            logger.info(f"Starting feedback agent run: {run_id}")

            # Record run start
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO system_runs (run_type, details)
                    VALUES ('feedback', :details)
                """), {
                    "details": json.dumps({"run_id": run_id, "timestamp": datetime.now().isoformat()})
                })

            # Execute feedback analysis
            feedback_tracker = TradeOutcomeTracker()
            result = feedback_tracker.analyze_recent_outcomes()

            # Record success
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE system_runs
                    SET end_time = CURRENT_TIMESTAMP, status = 'completed'
                    WHERE run_type = 'feedback' AND details->>'run_id' = :run_id
                """), {"run_id": run_id})

            logger.info(f"Feedback agent completed successfully: {run_id}")
            return AgentExecutionResult("feedback", True, f"Feedback agent completed: {run_id}",
                                      {"analysis_result": result is not None})

        except Exception as e:
            logger.error(f"Error executing feedback agent: {e}")

            # Record failure
            try:
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE system_runs
                        SET end_time = CURRENT_TIMESTAMP, status = 'failed'
                        WHERE run_type = 'feedback' AND details->>'run_id' = :run_id
                    """), {"run_id": run_id or "unknown"})
            except:
                pass

            return AgentExecutionResult("feedback", False, f"Feedback agent failed: {str(e)}")

    def execute_all_agents(self, run_id: Optional[str] = None) -> List[AgentExecutionResult]:
        """Execute all agents in sequence"""
        results = []

        # Execute summarizer first
        summarizer_result = self.execute_summarizer_agents(run_id)
        results.append(summarizer_result)

        if summarizer_result.success:
            # Small delay to ensure data is committed
            time.sleep(2)

            # Execute decider
            decider_result = self.execute_decider_agent(run_id)
            results.append(decider_result)

        # Execute feedback (always runs)
        feedback_result = self.execute_feedback_agent(run_id)
        results.append(feedback_result)

        return results

    def _get_unprocessed_summaries(self) -> List[Dict]:
        """Get unprocessed summaries for the current configuration"""
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT s.id, s.agent, s.timestamp, s.run_id, s.data
                FROM summaries s
                LEFT JOIN processed_summaries ps ON s.id = ps.summary_id AND ps.processed_by = 'decider'
                WHERE ps.summary_id IS NULL AND s.config_hash = :config_hash
                ORDER BY s.timestamp ASC
            """), {"config_hash": self.config_hash})
            return [row._mapping for row in result]

    def _mark_summaries_processed(self, summary_ids: List[int], processed_by: str):
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

# Global executor instance
agent_executor = UnifiedAgentExecutor()

# Convenience functions for easy access
def run_summarizer_agents(run_id: Optional[str] = None) -> AgentExecutionResult:
    """Convenience function to run summarizer agents"""
    return agent_executor.execute_summarizer_agents(run_id)

def run_decider_agent(run_id: Optional[str] = None) -> AgentExecutionResult:
    """Convenience function to run decider agent"""
    return agent_executor.execute_decider_agent(run_id)

def run_feedback_agent(run_id: Optional[str] = None) -> AgentExecutionResult:
    """Convenience function to run feedback agent"""
    return agent_executor.execute_feedback_agent(run_id)

def run_all_agents(run_id: Optional[str] = None) -> List[AgentExecutionResult]:
    """Convenience function to run all agents"""
    return agent_executor.execute_all_agents(run_id)
