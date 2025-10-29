"""
Safety checks and risk management for live trading
"""

import logging
from math import isfinite
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
from sqlalchemy import text
from config import (
    engine,
    MAX_POSITION_VALUE,
    MAX_POSITION_FRACTION,
    MAX_TOTAL_INVESTMENT,
    MAX_TOTAL_INVESTMENT_FRACTION,
    MIN_CASH_BUFFER,
    DEBUG_TRADING,
    get_current_config_hash,
)

logger = logging.getLogger(__name__)

class TradingSafetyManager:
    """
    Manages safety checks and risk limits for trading operations
    """
    
    def __init__(self):
        self.max_position_value = MAX_POSITION_VALUE
        self.max_position_fraction = MAX_POSITION_FRACTION
        self.max_total_investment = MAX_TOTAL_INVESTMENT
        self.max_total_investment_fraction = MAX_TOTAL_INVESTMENT_FRACTION
        self.min_cash_buffer = MIN_CASH_BUFFER
        
        # Additional safety limits
        self.max_daily_trades = 10  # Maximum trades per day
        self.max_position_percentage = 0.20  # Max 20% of portfolio in single position
        self.min_trade_value = 50  # Minimum trade value
        self.max_loss_percentage = 0.15  # Stop if daily loss exceeds 15%
        self.force_sell_loss_threshold = -0.03  # Force sell when loss >= 3%
        self.force_sell_gain_threshold = 0.05   # Force sell when gain >= 5%
        
        logger.info(f"TradingSafetyManager initialized with limits:")
        logger.info(f"  Max position value floor: ${self.max_position_value}")
        if self.max_position_fraction > 0:
            logger.info(f"  Max position fraction: {self.max_position_fraction:.0%} of account value")
        logger.info(f"  Max total investment floor: ${self.max_total_investment}")
        if self.max_total_investment_fraction > 0:
            logger.info(f"  Max total investment fraction: {self.max_total_investment_fraction:.0%} of account value")
        logger.info(f"  Min cash buffer: ${self.min_cash_buffer}")

    def _account_value(self, portfolio_value: float, current_cash: float) -> float:
        """
        Resolve account value for limit calculations. Portfolio value already includes
        cash for most runs; fall back to cash when portfolio value is unavailable.
        """
        if portfolio_value and portfolio_value > 0:
            return portfolio_value
        return max(current_cash, 0.0)

    def _resolve_position_limit(self, portfolio_value: float, current_cash: float) -> float:
        """
        Determine the active maximum position value, combining absolute and fractional limits.
        """
        limits = []
        if self.max_position_value > 0:
            limits.append(self.max_position_value)

        account_value = self._account_value(portfolio_value, current_cash)
        if self.max_position_fraction > 0 and account_value > 0:
            limits.append(account_value * self.max_position_fraction)

        return max(limits) if limits else float("inf")

    def _resolve_total_investment_limit(self, portfolio_value: float, current_cash: float) -> float:
        """
        Determine the active maximum total investment, combining absolute and fractional limits.
        """
        limits = []
        if self.max_total_investment > 0:
            limits.append(self.max_total_investment)

        account_value = self._account_value(portfolio_value, current_cash)
        if self.max_total_investment_fraction > 0 and account_value > 0:
            limits.append(account_value * self.max_total_investment_fraction)

        return max(limits) if limits else float("inf")

    def validate_trade_decision(self, 
                              decision: Dict, 
                              current_portfolio_value: float,
                              current_cash: float,
                              current_positions: List[Dict]) -> Tuple[bool, str]:
        """
        Validate a single trade decision against safety limits
        
        Args:
            decision: Trading decision dict
            current_portfolio_value: Total portfolio value
            current_cash: Available cash
            current_positions: List of current positions
            
        Returns:
            Tuple of (is_valid, reason)
        """
        try:
            action = decision.get("action", "").lower()
            ticker = decision.get("ticker", "")
            amount_usd = float(decision.get("amount_usd", 0))
            
            if not ticker:
                return False, "Missing ticker symbol"
            
            if amount_usd <= 0:
                return False, "Invalid trade amount"
            
            # Check minimum trade value
            if amount_usd < self.min_trade_value:
                return False, f"Trade value ${amount_usd:.2f} below minimum ${self.min_trade_value}"
            
            if action == "buy":
                return self._validate_buy_order(
                    decision,
                    ticker,
                    amount_usd,
                    current_portfolio_value,
                    current_cash,
                    current_positions,
                )
            elif action == "sell":
                return self._validate_sell_order(
                    ticker, amount_usd, current_positions
                )
            else:
                return False, f"Unknown action: {action}"
                
        except Exception as e:
            logger.error(f"Error validating trade decision: {e}")
            return False, f"Validation error: {str(e)}"
    
    def _validate_buy_order(self,
                           decision: Dict,
                           ticker: str,
                           amount_usd: float,
                           portfolio_value: float,
                           current_cash: float,
                           positions: List[Dict]) -> Tuple[bool, str]:
        """Validate buy order against safety limits (auto-resize when needed)."""

        existing_position = next(
            (p for p in positions if (p.get("symbol") or "").upper() == ticker.upper()),
            None,
        )
        existing_position_value = float(existing_position.get("market_value", 0)) if existing_position else 0.0
        total_positions_value = sum(float(p.get("market_value", 0)) for p in positions)

        cash_capacity = max(0.0, current_cash - self.min_cash_buffer)

        position_limit = self._resolve_position_limit(portfolio_value, current_cash)
        if isfinite(position_limit):
            position_capacity = max(0.0, position_limit - existing_position_value)
        else:
            position_capacity = float("inf")

        if portfolio_value > 0 and self.max_position_percentage > 0:
            max_pct_value = self.max_position_percentage * portfolio_value
            pct_capacity = max(0.0, max_pct_value - existing_position_value)
        else:
            pct_capacity = float("inf")

        total_limit = self._resolve_total_investment_limit(portfolio_value, current_cash)
        if isfinite(total_limit):
            remaining_total_capacity = max(0.0, total_limit - total_positions_value)
        else:
            remaining_total_capacity = float("inf")

        allowed_amount = min(cash_capacity, position_capacity, pct_capacity, remaining_total_capacity)

        if allowed_amount <= 0:
            return False, "No capacity available for additional buying"

        adjusted = False
        original_amount = amount_usd
        if amount_usd > allowed_amount:
            if allowed_amount < self.min_trade_value:
                return False, (
                    f"Trade would exceed limits; remaining capacity ${allowed_amount:.2f} is below minimum ${self.min_trade_value:.2f}"
                )
            amount_usd = round(allowed_amount, 2)
            decision["amount_usd"] = amount_usd
            adjusted = True

        if amount_usd <= 0:
            return False, "Adjusted trade amount is zero"

        if amount_usd + self.min_cash_buffer > current_cash:
            return False, f"Insufficient cash after adjustment: ${current_cash:.2f} available"

        if not self._check_daily_trade_limit():
            return False, "Daily trade limit exceeded"

        if adjusted:
            return True, f"Buy resized to ${amount_usd:.2f} (requested ${original_amount:.2f})"
        return True, "Buy order validated"
    
    def _validate_sell_order(self, 
                            ticker: str, 
                            amount_usd: float,
                            positions: List[Dict]) -> Tuple[bool, str]:
        """Validate sell order against safety limits"""
        
        # Find the position
        position = next((p for p in positions if p.get("symbol") == ticker), None)
        if not position:
            return False, f"No position found for {ticker}"
        
        # Check if we have enough shares to sell
        position_value = position.get("market_value", 0)
        if position_value == 0:
            return False, f"No value in position for {ticker}"
        
        # For now, assume selling entire position (can be refined later)
        try:
            pos_current = float(position.get('current_value') or position.get('market_value') or 0.0)
            pos_cost = float(position.get('total_value') or 0.0)
            if pos_cost > 0:
                pnl_ratio = (pos_current - pos_cost) / pos_cost
                if pnl_ratio >= self.force_sell_gain_threshold:
                    return True, f"Auto-sell to harvest gains: position up {pnl_ratio*100:.2f}%"
                if pnl_ratio <= self.force_sell_loss_threshold:
                    return True, f"Auto-sell stop loss: position down {abs(pnl_ratio)*100:.2f}%"
        except Exception:
            pass
        # In practice, you'd calculate based on amount_usd vs current price
        
        return True, "Sell order validated"
    
    def _check_daily_trade_limit(self) -> bool:
        """Check if daily trade limit has been exceeded"""
        try:
            today = datetime.now().date()
            with engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT COUNT(*) as trade_count
                    FROM trade_decisions 
                    WHERE DATE(timestamp) = :today AND config_hash = :config_hash
                """), {"today": today, "config_hash": get_current_config_hash()})
                
                trade_count = result.fetchone().trade_count
                return trade_count < self.max_daily_trades
                
        except Exception as e:
            logger.error(f"Error checking daily trade limit: {e}")
            return False  # Err on the side of caution
    
    def check_portfolio_health(self, 
                              current_value: float, 
                              initial_value: float) -> Tuple[bool, List[str]]:
        """
        Check overall portfolio health and risk metrics
        
        Args:
            current_value: Current portfolio value
            initial_value: Initial portfolio value
            
        Returns:
            Tuple of (is_healthy, list_of_warnings)
        """
        warnings = []
        is_healthy = True
        
        try:
            # Check for excessive losses
            if initial_value > 0:
                loss_percentage = (initial_value - current_value) / initial_value
                if loss_percentage > self.max_loss_percentage:
                    warnings.append(f"Portfolio loss of {loss_percentage*100:.1f}% exceeds limit of {self.max_loss_percentage*100:.1f}%")
                    is_healthy = False
            
            # Check cash buffer
            with engine.begin() as conn:
                cash_result = conn.execute(text("""
                    SELECT current_value FROM holdings WHERE ticker = 'CASH' AND config_hash = :config_hash
                """), {"config_hash": get_current_config_hash()})
                cash_row = cash_result.fetchone()
                
                if cash_row:
                    cash_balance = float(cash_row.current_value)
                    if cash_balance < self.min_cash_buffer:
                        warnings.append(f"Cash balance ${cash_balance:.2f} below minimum buffer ${self.min_cash_buffer}")
                        is_healthy = False
            
            # Check for over-concentration
            with engine.begin() as conn:
                positions_result = conn.execute(text("""
                    SELECT ticker, current_value, (current_value / :total_value) * 100 as percentage
                    FROM holdings 
                    WHERE is_active = TRUE AND ticker != 'CASH'
                    AND current_value > 0
                """), {"total_value": current_value})
                
                for row in positions_result:
                    if row.percentage > self.max_position_percentage * 100:
                        warnings.append(f"{row.ticker} represents {row.percentage:.1f}% of portfolio (max {self.max_position_percentage*100:.1f}%)")
            
            return is_healthy, warnings
            
        except Exception as e:
            logger.error(f"Error checking portfolio health: {e}")
            return False, [f"Health check error: {str(e)}"]
    
    def get_trading_status(self) -> Dict:
        """Get current trading status and limits"""
        try:
            # Get current portfolio stats
            with engine.begin() as conn:
                # Get total portfolio value
                portfolio_result = conn.execute(text("""
                    SELECT SUM(current_value) as total_value
                    FROM holdings WHERE is_active = TRUE
                """))
                portfolio_row = portfolio_result.fetchone()
                total_value = float(portfolio_row.total_value) if portfolio_row and portfolio_row.total_value else 0
                
                # Get cash balance
                cash_result = conn.execute(text("""
                    SELECT current_value FROM holdings WHERE ticker = 'CASH' AND config_hash = :config_hash
                """), {"config_hash": get_current_config_hash()})
                cash_row = cash_result.fetchone()
                cash_balance = float(cash_row.current_value) if cash_row else 0
                
                # Get today's trade count
                today = datetime.now().date()
                trades_result = conn.execute(text("""
                    SELECT COUNT(*) as trade_count
                    FROM trade_decisions 
                    WHERE DATE(timestamp) = :today AND config_hash = :config_hash
                """), {"today": today, "config_hash": get_current_config_hash()})
                trades_row = trades_result.fetchone()
                daily_trades = trades_row.trade_count if trades_row else 0
            position_limit = self._resolve_position_limit(total_value, cash_balance)
            total_limit = self._resolve_total_investment_limit(total_value, cash_balance)

            return {
                "portfolio_value": total_value,
                "cash_balance": cash_balance,
                "daily_trades": daily_trades,
                "limits": {
                    "max_position_value": position_limit if isfinite(position_limit) else None,
                    "max_total_investment": total_limit if isfinite(total_limit) else None,
                    "max_position_value_floor": self.max_position_value if self.max_position_value > 0 else None,
                    "max_position_fraction": self.max_position_fraction if self.max_position_fraction > 0 else None,
                    "max_total_investment_floor": self.max_total_investment if self.max_total_investment > 0 else None,
                    "max_total_investment_fraction": self.max_total_investment_fraction if self.max_total_investment_fraction > 0 else None,
                    "min_cash_buffer": self.min_cash_buffer,
                    "max_daily_trades": self.max_daily_trades,
                    "max_position_percentage": self.max_position_percentage * 100,
                    "min_trade_value": self.min_trade_value
                },
                "status": "healthy" if cash_balance >= self.min_cash_buffer and daily_trades < self.max_daily_trades else "warning"
            }
            
        except Exception as e:
            logger.error(f"Error getting trading status: {e}")
            return {
                "error": str(e),
                "status": "error"
            }

# Global safety manager instance
safety_manager = TradingSafetyManager()
