"""
Trading Interface - Abstraction layer for trading operations
Handles both simulation (dashboard) and live (Schwab API) trading
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from sqlalchemy import text
from config import engine, TRADING_MODE, DEBUG_TRADING, get_current_config_hash, SCHWAB_ACCOUNT_HASH
from schwab_client import schwab_client, get_portfolio_snapshot
from schwab_ledger import compute_effective_funds, components as ledger_components
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
        self.live_view_only = os.environ.get("DAI_SCHWAB_LIVE_VIEW", "0") == "1"
        self.readonly_mode = os.environ.get("DAI_SCHWAB_READONLY", "0") == "1"
        
        # Initialize Schwab client if we are trading live OR have been asked to run live view
        if self.trading_mode in {"live", "real_world"} or self.live_view_only:
            try:
                self.schwab_enabled = schwab_client.authenticate()
                if self.schwab_enabled:
                    logger.info("Schwab API client authenticated successfully")
                else:
                    logger.error("Failed to authenticate Schwab API client")
                    print(
                        "⚠️ Schwab authentication failed. "
                        "Run ./test_schwab_api.sh to complete re-authentication (browser OAuth required)."
                    )
            except Exception as e:
                logger.error(f"Error initializing Schwab client: {e}")
                self.schwab_enabled = False
                print(
                    "⚠️ Unable to initialize Schwab client. "
                    "Try re-running ./test_schwab_api.sh to refresh credentials."
                )
        
        logger.info(
            "TradingInterface initialized - Mode: %s, Schwab Enabled: %s, Live View: %s, Read-Only: %s",
            self.trading_mode,
            self.schwab_enabled,
            self.live_view_only,
            self.readonly_mode
        )
    
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
            if self.trading_mode in {"live", "real_world"} and self.schwab_enabled:
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
            update_holdings(decisions, skip_live_execution=(self.trading_mode in {"live", "real_world"}))
            
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
    
    @staticmethod
    def _wrap_live_result(result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalise Schwab live execution responses for legacy callers.
        """
        if not isinstance(result, dict):
            return {
                "success": False,
                "status": "error",
                "error": "Unknown Schwab order response",
            }

        payload = dict(result)
        status = payload.get("status")
        if status == "success":
            payload["success"] = True
        else:
            payload["success"] = False
            payload.setdefault("error", payload.get("reason", "Order not executed"))
        return payload

    def execute_buy_order(self, ticker: str, amount_usd: float, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Place a market buy order using USD allocation (legacy helper for decider_agent).
        """
        decision = {
            "action": "buy",
            "ticker": ticker,
            "amount_usd": amount_usd,
            "reason": reason or "",
        }
        return self._wrap_live_result(self._execute_schwab_order(decision))

    def execute_sell_order(self, ticker: str, shares: float, reason: Optional[str] = None) -> Dict[str, Any]:
        """
        Place a market sell order for an explicit share count (legacy helper for decider_agent).
        """
        try:
            shares_int = int(float(shares))
        except (TypeError, ValueError):
            return {
                "success": False,
                "status": "error",
                "error": f"Invalid share quantity: {shares}",
                "ticker": ticker,
            }

        if shares_int <= 0:
            return {
                "success": False,
                "status": "error",
                "error": f"Share quantity must be positive (got {shares_int})",
                "ticker": ticker,
            }

        decision = {
            "action": "sell",
            "ticker": ticker,
            "shares_override": shares_int,
            "amount_usd": 0.0,
            "reason": reason or "",
        }
        return self._wrap_live_result(self._execute_schwab_order(decision))

    def _execute_schwab_order(self, decision: Dict) -> Dict:
        """
        Execute a single order through Schwab API
        """
        try:
            action = decision.get("action", "").lower()
            ticker = decision.get("ticker", "")
            reason = decision.get("reason", "")
            if not ticker:
                return {
                    "status": "error",
                    "error": "Invalid ticker",
                    "execution_type": "live",
                    "decision": decision
                }

            amount_usd = float(decision.get("amount_usd", 0))
            
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
                if amount_usd <= 0:
                    return {
                        "status": "error",
                        "error": "Invalid allocation amount",
                        "execution_type": "live",
                        "decision": decision
                    }
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
                shares_override = decision.get("shares_override")
                if shares_override is not None:
                    try:
                        shares = int(float(shares_override))
                    except (TypeError, ValueError):
                        return {
                            "status": "error",
                            "error": f"Invalid share override: {shares_override}",
                            "execution_type": "live",
                            "decision": decision,
                        }
                else:
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
    
    def sync_schwab_positions(self, persist: bool = False) -> Dict[str, Any]:
        """
        Sync positions from Schwab API for the dashboard
        """
        try:
            if not self.schwab_enabled:
                try:
                    if schwab_client.ensure_authenticated(force=False):
                        self.schwab_enabled = True
                    else:
                        if self.live_view_only or os.environ.get("DAI_SCHWAB_LIVE_VIEW", "0") == "1":
                            print(
                                "⚠️ Schwab live view authentication failed. "
                                "Run ./test_schwab_api.sh to refresh Schwab OAuth tokens."
                            )
                        return {
                            "status": "disabled",
                            "message": "Schwab API not enabled"
                        }
                except Exception as auth_err:
                    logger.error(f"Unable to authenticate Schwab client: {auth_err}")
                    if self.live_view_only or os.environ.get("DAI_SCHWAB_LIVE_VIEW", "0") == "1":
                        print(
                            "⚠️ Schwab live view authentication failed. "
                            "Run ./test_schwab_api.sh to refresh Schwab OAuth tokens."
                        )
                    return {
                        "status": "disabled",
                        "message": "Schwab API not enabled"
                    }

            if not schwab_client.ensure_authenticated():
                self.schwab_enabled = False
                return {
                    "status": "error",
                    "message": "Schwab authentication expired; refresh token required"
                }
            
            logger.info(
                "Fetching Schwab portfolio snapshot (live_view=%s, trading_mode=%s)",
                self.live_view_only,
                self.trading_mode,
            )
            print("🔍 sync_schwab_positions: requesting account snapshot...")
            portfolio = get_portfolio_snapshot()
            if not portfolio:
                print("⚠️ sync_schwab_positions: no portfolio snapshot returned")
                return {
                    "status": "error",
                    "message": "Could not get Schwab portfolio snapshot"
                }

            formatted_positions = portfolio.get("positions", [])
            settled_positions = portfolio.get("settled_positions", [])
            balances_raw = portfolio.get("balances_raw", {})
            positions_raw = portfolio.get("positions_raw", [])
            ledger_state = portfolio.get("ledger_state")
            ledger_comp = portfolio.get("ledger_components") or ledger_components()

            total_value = sum(p.get("market_value", 0) for p in formatted_positions)

            cash_balance_settled = portfolio.get("cash_balance_settled", portfolio.get("cash_balance", 0.0))
            unsettled_cash = portfolio.get("unsettled_cash", 0.0)
            same_day_net = portfolio.get("same_day_net_activity", ledger_comp.get("same_day_net", 0.0))
            order_reserve = portfolio.get("order_reserve", ledger_comp.get("open_buy_reserve", 0.0))

            baseline_cash = portfolio.get("funds_available_explicit")
            if baseline_cash is None:
                baseline_cash = portfolio.get("funds_available_raw", cash_balance_settled)
            explicit_cash = baseline_cash
            derived_cash = portfolio.get("funds_available_derived", baseline_cash)
            effective_cash = compute_effective_funds(baseline_cash)

            buying_power = portfolio.get("buying_power", effective_cash)
            day_trading_power = portfolio.get("day_trading_power", 0.0)
            account_value = portfolio.get("account_value", total_value + effective_cash)

            print(
                f"💰 sync_schwab_positions: funds_available={effective_cash:.2f} "
                f"cash_settled={cash_balance_settled:.2f} unsettled_cash={unsettled_cash:.2f} "
                f"order_reserve={order_reserve:.2f} buying_power={buying_power:.2f} "
                f"day_trading_power={day_trading_power:.2f}"
            )
            if same_day_net:
                print(f"   ↳ same-day net activity contribution: {same_day_net:.2f}")

            result = {
                "status": "success",
                "positions": formatted_positions,
                "settled_positions": settled_positions,
                "cash_balance": cash_balance_settled,
                "cash_balance_settled": cash_balance_settled,
                "unsettled_cash": unsettled_cash,
                "funds_available_for_trading": effective_cash,
                "funds_available_effective": effective_cash,
                "funds_available_explicit": explicit_cash,
                "funds_available_derived": derived_cash,
                "same_day_net_activity": same_day_net,
                "order_reserve": order_reserve,
                "total_portfolio_value": total_value + effective_cash,
                "account_info": {
                    "account_value": account_value,
                    "buying_power": buying_power,
                    "day_trading_buying_power": day_trading_power,
                    "funds_available_for_trading": effective_cash,
                    "funds_available_explicit": explicit_cash,
                    "funds_available_derived": derived_cash,
                    "same_day_net_activity": same_day_net,
                    "cash_balance": cash_balance_settled,
                    "unsettled_cash": unsettled_cash,
                    "order_reserve": order_reserve,
                    "balances_raw": balances_raw,
                    "positions_raw": positions_raw,
                    "account_hash": portfolio.get("account_hash") or SCHWAB_ACCOUNT_HASH,
                    "account_number": portfolio.get("account_number"),
                    "account_type": portfolio.get("account_type"),
                },
                "positions_count": len(formatted_positions),
                "last_updated": datetime.now().isoformat(),
                "readonly_mode": self.readonly_mode,
                "live_trading_enabled": (self.trading_mode in {"live", "real_world"}) and not self.readonly_mode,
                "funds_available_components": {
                    "effective": effective_cash,
                    "explicit": explicit_cash,
                    "derived_cash": derived_cash,
                    "settled_cash": cash_balance_settled,
                    "unsettled_cash": unsettled_cash,
                    "same_day_net": same_day_net,
                    "order_reserve": order_reserve,
                },
                "ledger_state": ledger_state,
                "ledger_components": ledger_comp,
                "transactions_sample": portfolio.get("transactions_sample")
            }
            if persist:
                try:
                    self._persist_live_snapshot(formatted_positions, cash_balance_settled, result)
                except Exception as persist_err:
                    logger.error("Failed to persist live Schwab snapshot: %s", persist_err)
            return result
            
        except Exception as e:
            logger.error(f"Error syncing Schwab positions: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def _persist_live_snapshot(self, positions: List[Dict[str, Any]], cash_balance: float, snapshot: Dict[str, Any]) -> None:
        """
        Write live Schwab holdings and portfolio snapshot into the database so charts & prompts use real balances.
        """
        config_hash = get_current_config_hash()
        now = datetime.utcnow()

        processed_holdings = []
        total_invested = 0.0
        total_current = 0.0

        for position in positions:
            shares = float(position.get("shares") or 0.0)
            avg_price = float(position.get("average_price") or 0.0)
            current_price = float(position.get("current_price") or 0.0)
            total_value = float(position.get("total_value") or (shares * avg_price))
            current_value = float(position.get("market_value") or (shares * current_price))
            gain_loss = float(position.get("gain_loss") or (current_value - total_value))

            processed_holdings.append({
                "ticker": position.get("symbol", "-").upper(),
                "shares": shares,
                "purchase_price": avg_price,
                "current_price": current_price,
                "total_value": total_value,
                "current_value": current_value,
                "gain_loss": gain_loss,
                "reason": "Schwab synced position",
            })

            total_invested += total_value
            total_current += current_value

        holdings_snapshot = json.dumps([
            {"ticker": h["ticker"], "current_value": h["current_value"]}
            for h in processed_holdings
        ])

        total_portfolio_value = total_current + float(cash_balance)
        total_profit_loss = total_current - total_invested
        percentage_gain = (total_profit_loss / total_invested * 100.0) if total_invested else 0.0

        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM holdings WHERE config_hash = :config_hash"),
                {"config_hash": config_hash},
            )
            conn.execute(text("""
                INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price,
                                      purchase_timestamp, current_price_timestamp, total_value, current_value,
                                      gain_loss, reason, is_active)
                VALUES (:config_hash, 'CASH', 1, :cash, :cash, :ts, :ts, :cash, :cash, 0, 'Schwab cash balance', TRUE)
            """), {
                "config_hash": config_hash,
                "cash": float(cash_balance),
                "ts": now,
            })

            for holding in processed_holdings:
                conn.execute(text("""
                    INSERT INTO holdings (config_hash, ticker, shares, purchase_price, current_price,
                                          purchase_timestamp, current_price_timestamp, total_value, current_value,
                                          gain_loss, reason, is_active)
                    VALUES (:config_hash, :ticker, :shares, :purchase_price, :current_price,
                            :ts, :ts, :total_value, :current_value, :gain_loss, :reason, TRUE)
                """), {
                    "config_hash": config_hash,
                    "ticker": holding["ticker"],
                    "shares": holding["shares"],
                    "purchase_price": holding["purchase_price"],
                    "current_price": holding["current_price"],
                    "total_value": holding["total_value"],
                    "current_value": holding["current_value"],
                    "gain_loss": holding["gain_loss"],
                    "reason": holding["reason"],
                    "ts": now,
                })

            conn.execute(text("""
                INSERT INTO portfolio_history
                (total_portfolio_value, cash_balance, total_invested,
                 total_profit_loss, percentage_gain, holdings_snapshot, config_hash)
                VALUES (:total_portfolio_value, :cash_balance, :total_invested,
                        :total_profit_loss, :percentage_gain, :holdings_snapshot, :config_hash)
            """), {
                "total_portfolio_value": total_portfolio_value,
                "cash_balance": float(cash_balance),
                "total_invested": total_invested,
                "total_profit_loss": total_profit_loss,
                "percentage_gain": percentage_gain,
                "holdings_snapshot": holdings_snapshot,
                "config_hash": config_hash,
            })
    
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
