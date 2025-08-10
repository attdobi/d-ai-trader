"""
Safety checks and risk management for live trading
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy import text
from config import (
    engine, MAX_POSITION_VALUE, MAX_TOTAL_INVESTMENT, 
    MIN_CASH_BUFFER, DEBUG_TRADING
)

logger = logging.getLogger(__name__)

class TradingSafetyManager:
    """
    Manages safety checks and risk limits for trading operations
    """
    
    def __init__(self):
        self.max_position_value = MAX_POSITION_VALUE
        self.max_total_investment = MAX_TOTAL_INVESTMENT
        self.min_cash_buffer = MIN_CASH_BUFFER
        
        # Additional safety limits
        self.max_daily_trades = 10  # Maximum trades per day
        self.max_position_percentage = 0.20  # Max 20% of portfolio in single position
        self.min_trade_value = 50  # Minimum trade value
        self.max_loss_percentage = 0.15  # Stop if daily loss exceeds 15%
        
        logger.info(f"TradingSafetyManager initialized with limits:")
        logger.info(f"  Max position value: ${self.max_position_value}")
        logger.info(f"  Max total investment: ${self.max_total_investment}")
        logger.info(f"  Min cash buffer: ${self.min_cash_buffer}")
    
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
                    ticker, amount_usd, current_portfolio_value, 
                    current_cash, current_positions
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
                           ticker: str, 
                           amount_usd: float,
                           portfolio_value: float,
                           current_cash: float,
                           positions: List[Dict]) -> Tuple[bool, str]:
        """Validate buy order against safety limits"""
        
        # Check if we have enough cash (including buffer)
        if current_cash < amount_usd + self.min_cash_buffer:
            return False, f"Insufficient cash: ${current_cash:.2f} available, need ${amount_usd + self.min_cash_buffer:.2f}"
        
        # Check maximum position value
        if amount_usd > self.max_position_value:
            return False, f"Position value ${amount_usd:.2f} exceeds maximum ${self.max_position_value}"
        
        # Check position concentration (percentage of portfolio)
        if portfolio_value > 0:
            position_percentage = amount_usd / portfolio_value
            if position_percentage > self.max_position_percentage:
                return False, f"Position would be {position_percentage*100:.1f}% of portfolio (max {self.max_position_percentage*100:.1f}%)"
        
        # Check if adding to existing position
        existing_position = next((p for p in positions if p.get("symbol") == ticker), None)
        if existing_position:
            total_position_value = existing_position.get("market_value", 0) + amount_usd
            if total_position_value > self.max_position_value:
                return False, f"Total position value would be ${total_position_value:.2f} (max ${self.max_position_value})"
        
        # Check total investment limit
        total_invested = sum(p.get("market_value", 0) for p in positions) + amount_usd
        if total_invested > self.max_total_investment:
            return False, f"Total investment would be ${total_invested:.2f} (max ${self.max_total_investment})"
        
        # Check daily trade limit
        if not self._check_daily_trade_limit():
            return False, "Daily trade limit exceeded"
        
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
                    WHERE DATE(timestamp) = :today
                """), {"today": today})
                
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
                    SELECT current_value FROM holdings WHERE ticker = 'CASH'
                """))
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
                    SELECT current_value FROM holdings WHERE ticker = 'CASH'
                """))
                cash_row = cash_result.fetchone()
                cash_balance = float(cash_row.current_value) if cash_row else 0
                
                # Get today's trade count
                today = datetime.now().date()
                trades_result = conn.execute(text("""
                    SELECT COUNT(*) as trade_count
                    FROM trade_decisions 
                    WHERE DATE(timestamp) = :today
                """), {"today": today})
                trades_row = trades_result.fetchone()
                daily_trades = trades_row.trade_count if trades_row else 0
            
            return {
                "portfolio_value": total_value,
                "cash_balance": cash_balance,
                "daily_trades": daily_trades,
                "limits": {
                    "max_position_value": self.max_position_value,
                    "max_total_investment": self.max_total_investment,
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
