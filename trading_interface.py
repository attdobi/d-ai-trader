"""
Trading Interface - Abstraction layer for trading operations
Handles both simulation (dashboard) and live (Schwab API) trading
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from sqlalchemy import text
from config import engine, TRADING_MODE, DEBUG_TRADING, get_current_config_hash
from schwab_client import schwab_client
from feedback_agent import TradeOutcomeTracker
from safety_checks import safety_manager

logger = logging.getLogger(__name__)

class TradingInterface:
    """
    Unified trading interface that handles both simulation and live trading
    """
    
    def __init__(self):
        self.trading_mode = TRADING_MODE
        self.feedback_tracker = TradeOutcomeTracker()
        self.schwab_enabled = False
        
        # Initialize Schwab client if in live mode
        if self.trading_mode == "live":
            try:
                self.schwab_enabled = schwab_client.authenticate()
                if self.schwab_enabled:
                    logger.info("Schwab API client authenticated successfully")
                else:
                    logger.error("Failed to authenticate Schwab API client")
            except Exception as e:
                logger.error(f"Error initializing Schwab client: {e}")
                self.schwab_enabled = False
        
        logger.info(f"TradingInterface initialized - Mode: {self.trading_mode}, Schwab: {self.schwab_enabled}")
    
    def execute_trade_decisions(self, decisions: List[Dict]) -> Dict[str, Any]:
        """
        Execute trading decisions in both simulation (dashboard) and optionally live (Schwab)
        
        Args:
            decisions: List of trading decisions from the AI agent
            
        Returns:
            Dictionary with execution results
        """
        results = {
            "simulation_results": [],
            "live_results": [],
            "errors": [],
            "safety_checks": [],
            "summary": {
                "total_decisions": len(decisions),
                "simulation_executed": 0,
                "live_executed": 0,
                "skipped": 0,
                "errors": 0,
                "safety_violations": 0
            }
        }
        
        try:
            # Always execute in simulation (update dashboard database)
            sim_results = self._execute_simulation_trades(decisions)
            results["simulation_results"] = sim_results
            
            # Count simulation results
            for result in sim_results:
                if result.get("status") == "executed":
                    results["summary"]["simulation_executed"] += 1
                elif result.get("status") == "skipped":
                    results["summary"]["skipped"] += 1
                else:
                    results["summary"]["errors"] += 1
            
            # Execute in live trading if enabled
            if self.trading_mode == "live" and self.schwab_enabled:
                # Run safety checks before live trading
                safe_decisions, safety_results = self._run_safety_checks(decisions)
                results["safety_checks"] = safety_results
                
                if safe_decisions:
                    live_results = self._execute_live_trades(safe_decisions)
                    results["live_results"] = live_results
                else:
                    logger.warning("All live trades blocked by safety checks")
                    results["live_results"] = [{
                        "status": "blocked",
                        "reason": "All trades blocked by safety checks",
                        "execution_type": "live"
                    }]
                
                # Count live results
                for result in live_results:
                    if result.get("status") == "success":
                        results["summary"]["live_executed"] += 1
                    elif result.get("status") == "skipped":
                        results["summary"]["skipped"] += 1
                    else:
                        results["summary"]["errors"] += 1
            
            logger.info(f"Trade execution completed: {results['summary']}")
            return results
            
        except Exception as e:
            logger.error(f"Error executing trade decisions: {e}")
            results["errors"].append(str(e))
            results["summary"]["errors"] += 1
            return results
    
    def _execute_simulation_trades(self, decisions: List[Dict]) -> List[Dict]:
        """
        Execute trades in simulation mode (update dashboard database)
        This mirrors the existing update_holdings function logic
        """
        from decider_agent import update_holdings
        
        try:
            logger.info(f"Executing {len(decisions)} decisions in simulation mode")
            
            # Use the existing update_holdings function
            update_holdings(decisions)
            
            # Return success results for all decisions
            results = []
            for decision in decisions:
                results.append({
                    "status": "executed",
                    "action": decision.get("action"),
                    "ticker": decision.get("ticker"),
                    "amount_usd": decision.get("amount_usd"),
                    "reason": decision.get("reason"),
                    "execution_type": "simulation",
                    "timestamp": datetime.now().isoformat()
                })
            
            return results
            
        except Exception as e:
            logger.error(f"Error in simulation trading: {e}")
            return [{
                "status": "error",
                "error": str(e),
                "execution_type": "simulation"
            }]
    
    def _execute_live_trades(self, decisions: List[Dict]) -> List[Dict]:
        """
        Execute trades through Schwab API
        """
        results = []
        
        try:
            if not self.schwab_enabled:
                logger.warning("Schwab API not enabled, skipping live trades")
                return [{
                    "status": "skipped",
                    "reason": "Schwab API not enabled",
                    "execution_type": "live"
                }]
            
            logger.info(f"Executing {len(decisions)} decisions in live mode via Schwab API")
            
            # Process sells first, then buys (same as simulation)
            sell_decisions = [d for d in decisions if d.get("action", "").lower() == "sell"]
            buy_decisions = [d for d in decisions if d.get("action", "").lower() == "buy"]
            
            # Execute sell orders
            for decision in sell_decisions:
                result = self._execute_schwab_order(decision)
                results.append(result)
            
            # Wait between sells and buys if both exist
            if sell_decisions and buy_decisions:
                logger.info("Waiting 30 seconds between sells and buys...")
                time.sleep(30)
            
            # Execute buy orders
            for decision in buy_decisions:
                result = self._execute_schwab_order(decision)
                results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Error in live trading: {e}")
            return [{
                "status": "error",
                "error": str(e),
                "execution_type": "live"
            }]
    
    def _execute_schwab_order(self, decision: Dict) -> Dict:
        """
        Execute a single order through Schwab API
        """
        try:
            action = decision.get("action", "").lower()
            ticker = decision.get("ticker", "")
            amount_usd = float(decision.get("amount_usd", 0))
            reason = decision.get("reason", "")
            
            if not ticker or amount_usd <= 0:
                return {
                    "status": "error",
                    "error": "Invalid ticker or amount",
                    "execution_type": "live",
                    "decision": decision
                }
            
            # Get current price to calculate shares
            from decider_agent import get_current_price
            current_price = get_current_price(ticker)
            
            if not current_price:
                return {
                    "status": "error",
                    "error": "Could not get current price",
                    "execution_type": "live",
                    "decision": decision
                }
            
            if action == "buy":
                # Calculate number of shares to buy
                shares = int(amount_usd / current_price)
                if shares == 0:
                    return {
                        "status": "skipped",
                        "reason": "Insufficient funds for 1 share",
                        "execution_type": "live",
                        "decision": decision
                    }
                
                # Place buy order
                order_result = schwab_client.place_equity_order(
                    symbol=ticker,
                    quantity=shares,
                    instruction="BUY",
                    order_type="MARKET"
                )
                
            elif action == "sell":
                # For sells, we need to get current position to know how many shares to sell
                positions = schwab_client.get_positions()
                if not positions:
                    return {
                        "status": "error",
                        "error": "Could not get current positions",
                        "execution_type": "live",
                        "decision": decision
                    }
                
                # Find the position for this ticker
                position = None
                for pos in positions:
                    instrument = pos.get("instrument", {})
                    if instrument.get("symbol") == ticker:
                        position = pos
                        break
                
                if not position:
                    return {
                        "status": "skipped",
                        "reason": f"No position found for {ticker}",
                        "execution_type": "live",
                        "decision": decision
                    }
                
                shares = int(position.get("longQuantity", 0))
                if shares == 0:
                    return {
                        "status": "skipped",
                        "reason": f"No shares to sell for {ticker}",
                        "execution_type": "live",
                        "decision": decision
                    }
                
                # Place sell order
                order_result = schwab_client.place_equity_order(
                    symbol=ticker,
                    quantity=shares,
                    instruction="SELL",
                    order_type="MARKET"
                )
            
            else:
                return {
                    "status": "skipped",
                    "reason": f"Unknown action: {action}",
                    "execution_type": "live",
                    "decision": decision
                }
            
            if order_result and order_result.get("status") == "success":
                return {
                    "status": "success",
                    "order_id": order_result.get("order_id"),
                    "symbol": ticker,
                    "shares": shares,
                    "action": action,
                    "price": current_price,
                    "execution_type": "live",
                    "timestamp": datetime.now().isoformat(),
                    "reason": reason
                }
            else:
                return {
                    "status": "error",
                    "error": f"Order placement failed: {order_result}",
                    "execution_type": "live",
                    "decision": decision
                }
                
        except Exception as e:
            logger.error(f"Error executing Schwab order: {e}")
            return {
                "status": "error",
                "error": str(e),
                "execution_type": "live",
                "decision": decision
            }
    
    def sync_schwab_positions(self) -> Dict[str, Any]:
        """
        Sync positions from Schwab API for the dashboard
        """
        try:
            if not self.schwab_enabled:
                return {
                    "status": "disabled",
                    "message": "Schwab API not enabled"
                }
            
            # Get account info and positions
            account_info = schwab_client.get_account_info()
            if not account_info:
                return {
                    "status": "error",
                    "message": "Could not get account info"
                }
            
            securities_account = account_info.get("securitiesAccount", {})
            positions = securities_account.get("positions", [])
            balances = securities_account.get("currentBalances", {})
            
            # Format positions for dashboard
            formatted_positions = []
            total_value = 0
            
            for position in positions:
                instrument = position.get("instrument", {})
                symbol = instrument.get("symbol", "")
                
                if symbol and symbol != "CASH":
                    long_qty = float(position.get("longQuantity", 0))
                    market_value = float(position.get("marketValue", 0))
                    avg_price = float(position.get("averagePrice", 0))
                    
                    if long_qty > 0:
                        current_price = market_value / long_qty if long_qty > 0 else 0
                        gain_loss = market_value - (long_qty * avg_price)
                        gain_loss_pct = (gain_loss / (long_qty * avg_price)) * 100 if avg_price > 0 else 0
                        
                        formatted_positions.append({
                            "symbol": symbol,
                            "shares": long_qty,
                            "average_price": avg_price,
                            "current_price": current_price,
                            "market_value": market_value,
                            "gain_loss": gain_loss,
                            "gain_loss_percentage": gain_loss_pct,
                            "total_value": long_qty * avg_price
                        })
                        
                        total_value += market_value
            
            # Get cash balance
            cash_balance = float(balances.get("cashBalance", 0))
            
            return {
                "status": "success",
                "positions": formatted_positions,
                "cash_balance": cash_balance,
                "total_portfolio_value": total_value + cash_balance,
                "account_info": {
                    "account_value": float(balances.get("totalLongMarketValue", 0)),
                    "buying_power": float(balances.get("buyingPower", 0)),
                    "day_trading_buying_power": float(balances.get("dayTradingBuyingPower", 0))
                },
                "last_updated": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error syncing Schwab positions: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def _run_safety_checks(self, decisions: List[Dict]) -> tuple:
        """
        Run safety checks on trading decisions
        
        Args:
            decisions: List of trading decisions
            
        Returns:
            Tuple of (safe_decisions, safety_check_results)
        """
        safe_decisions = []
        safety_results = []
        
        try:
            # Get current portfolio state
            with engine.begin() as conn:
                # Get total portfolio value
                portfolio_result = conn.execute(text("""
                    SELECT SUM(current_value) as total_value
                    FROM holdings WHERE is_active = TRUE
                """))
                portfolio_row = portfolio_result.fetchone()
                portfolio_value = float(portfolio_row.total_value) if portfolio_row and portfolio_row.total_value else 0
                
                # Get cash balance
                cash_result = conn.execute(text("""
                    SELECT current_value FROM holdings WHERE ticker = 'CASH' AND config_hash = :config_hash
                """), {"config_hash": get_current_config_hash()})
                cash_row = cash_result.fetchone()
                cash_balance = float(cash_row.current_value) if cash_row else 0
                
                # Get current positions for safety checks
                positions_result = conn.execute(text("""
                    SELECT ticker as symbol, current_value as market_value, shares
                    FROM holdings 
                    WHERE is_active = TRUE AND ticker != 'CASH'
                """))
                positions = [dict(row._mapping) for row in positions_result]
            
            # Check each decision
            for decision in decisions:
                is_valid, reason = safety_manager.validate_trade_decision(
                    decision, portfolio_value, cash_balance, positions
                )
                
                safety_result = {
                    "decision": decision,
                    "is_valid": is_valid,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat()
                }
                safety_results.append(safety_result)
                
                if is_valid:
                    safe_decisions.append(decision)
                else:
                    logger.warning(f"Trade blocked by safety check: {reason}")
            
            # Check overall portfolio health
            initial_investment = 10000  # TODO: Get from config or database
            is_healthy, warnings = safety_manager.check_portfolio_health(
                portfolio_value, initial_investment
            )
            
            if not is_healthy:
                logger.warning(f"Portfolio health warnings: {warnings}")
                safety_results.append({
                    "type": "portfolio_health",
                    "is_healthy": is_healthy,
                    "warnings": warnings,
                    "timestamp": datetime.now().isoformat()
                })
                
                # If portfolio is unhealthy, block all new buys
                safe_decisions = [d for d in safe_decisions if d.get("action", "").lower() != "buy"]
                if len(safe_decisions) < len([d for d in decisions if d.get("action", "").lower() == "buy"]):
                    safety_results.append({
                        "type": "portfolio_protection",
                        "action": "blocked_buys",
                        "reason": "Portfolio health concerns - blocking new buy orders",
                        "timestamp": datetime.now().isoformat()
                    })
            
            logger.info(f"Safety checks: {len(safe_decisions)}/{len(decisions)} decisions approved")
            return safe_decisions, safety_results
            
        except Exception as e:
            logger.error(f"Error in safety checks: {e}")
            return [], [{
                "type": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }]

# Global trading interface instance
trading_interface = TradingInterface()
