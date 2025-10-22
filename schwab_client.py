"""
Schwab API Client for D-AI-Trader
Handles authentication, order placement, and account data retrieval
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
try:
    from schwab_api import SchwabAPI
    SCHWAB_AVAILABLE = True
except ImportError:
    SCHWAB_AVAILABLE = False
    SchwabAPI = None
from config import (
    SCHWAB_CLIENT_ID,
    SCHWAB_CLIENT_SECRET,
    SCHWAB_REDIRECT_URI,
    SCHWAB_ACCOUNT_HASH,
    TRADING_MODE,
    DEBUG_TRADING,
    MAX_POSITION_VALUE,
    MAX_POSITION_FRACTION,
    MAX_TOTAL_INVESTMENT,
    MAX_TOTAL_INVESTMENT_FRACTION,
    MIN_CASH_BUFFER,
)

logger = logging.getLogger(__name__)

class SchwabAPIClient:
    """
    Schwab API client for trading operations
    """
    
    def __init__(self):
        """Initialize the Schwab client"""
        self.client = None
        self.account_hash = SCHWAB_ACCOUNT_HASH
        self.is_authenticated = False
        self.trading_mode = TRADING_MODE
        self.token_file = "schwab_tokens.json"
        
        # Safety limits
        self.max_position_value = MAX_POSITION_VALUE
        self.max_position_fraction = MAX_POSITION_FRACTION
        self.max_total_investment = MAX_TOTAL_INVESTMENT
        self.max_total_investment_fraction = MAX_TOTAL_INVESTMENT_FRACTION
        self.min_cash_buffer = MIN_CASH_BUFFER
        
        if DEBUG_TRADING:
            logger.info(f"SchwabAPIClient initialized in {self.trading_mode} mode")
            logger.info(
                "Safety floors: position=$%s (fraction=%s), total=$%s (fraction=%s), cash buffer=$%s",
                self.max_position_value,
                f"{self.max_position_fraction:.0%}" if self.max_position_fraction > 0 else "disabled",
                self.max_total_investment,
                f"{self.max_total_investment_fraction:.0%}" if self.max_total_investment_fraction > 0 else "disabled",
                self.min_cash_buffer,
            )
    
    def authenticate(self) -> bool:
        """
        Authenticate with Schwab API using credentials
        Returns: True if authentication successful, False otherwise
        """
        try:
            if not SCHWAB_AVAILABLE:
                logger.error("Schwab API package not available")
                return False
                
            if not SCHWAB_CLIENT_ID or not SCHWAB_CLIENT_SECRET:
                logger.error("Schwab API credentials not configured")
                return False
            
            # Note: schwab-api package may require different authentication
            # This is a placeholder implementation that needs to be customized
            # based on the actual schwab-api package documentation
            
            logger.warning("Schwab API integration requires manual setup")
            logger.warning("Please refer to schwab-api package documentation")
            
            # For now, return False to use simulation mode
            self.is_authenticated = False
            return False
                
        except Exception as e:
            logger.error(f"Schwab authentication error: {e}")
            return False
    
    def get_accounts(self) -> Optional[List[Dict]]:
        """
        Get all accounts
        Returns: List of account data or None if error
        """
        try:
            if not self.client:
                return None
            
            response = self.client.get_account_numbers()
            if response.status_code == 200:
                accounts = response.json()
                return accounts
            else:
                logger.error(f"Failed to get accounts: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting accounts: {e}")
            return None
    
    def get_account_info(self, account_hash: Optional[str] = None) -> Optional[Dict]:
        """
        Get detailed account information
        Args:
            account_hash: Account to query, defaults to configured account
        Returns: Account data or None if error
        """
        try:
            if not self.client:
                return None
            
            acc_hash = account_hash or self.account_hash
            if not acc_hash:
                logger.error("No account hash provided")
                return None
            
            response = self.client.get_account(
                acc_hash,
                fields=schwab.client.Account.Fields.POSITIONS
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get account info: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting account info: {e}")
            return None
    
    def get_cash_balance(self, account_hash: Optional[str] = None) -> Optional[float]:
        """
        Get available cash balance
        Args:
            account_hash: Account to query, defaults to configured account
        Returns: Cash balance or None if error
        """
        try:
            account_info = self.get_account_info(account_hash)
            if not account_info:
                return None
            
            # Extract cash balance from account data
            securities_account = account_info.get('securitiesAccount', {})
            current_balances = securities_account.get('currentBalances', {})
            cash_balance = current_balances.get('cashBalance', 0.0)
            
            return float(cash_balance)
            
        except Exception as e:
            logger.error(f"Error getting cash balance: {e}")
            return None
    
    def get_positions(self, account_hash: Optional[str] = None) -> Optional[List[Dict]]:
        """
        Get current positions
        Args:
            account_hash: Account to query, defaults to configured account
        Returns: List of positions or None if error
        """
        try:
            account_info = self.get_account_info(account_hash)
            if not account_info:
                return None
            
            securities_account = account_info.get('securitiesAccount', {})
            positions = securities_account.get('positions', [])
            
            return positions
            
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return None
    
    def place_equity_order(self, 
                          symbol: str, 
                          quantity: int, 
                          instruction: str,
                          order_type: str = "MARKET",
                          price: Optional[float] = None,
                          account_hash: Optional[str] = None) -> Optional[Dict]:
        """
        Place an equity order
        Args:
            symbol: Stock symbol (e.g., 'AAPL')
            quantity: Number of shares
            instruction: 'BUY' or 'SELL'
            order_type: 'MARKET' or 'LIMIT'
            price: Price for limit orders
            account_hash: Account to trade in, defaults to configured account
        Returns: Order confirmation or None if error
        """
        try:
            if not self.client or not self.is_authenticated:
                logger.error("Not authenticated with Schwab API")
                return None
            
            acc_hash = account_hash or self.account_hash
            if not acc_hash:
                logger.error("No account hash provided")
                return None
            
            # Safety check - ensure we're in live trading mode for real orders
            if self.trading_mode != "live":
                logger.warning(f"Trading mode is '{self.trading_mode}' - skipping real order placement")
                return {
                    "status": "skipped",
                    "reason": f"Trading mode is {self.trading_mode}, not live",
                    "symbol": symbol,
                    "quantity": quantity,
                    "instruction": instruction
                }
            
            # Create the order based on type and instruction
            if order_type.upper() == "MARKET":
                if instruction.upper() == "BUY":
                    order = equity_buy_market(symbol, quantity)
                else:  # SELL
                    order = equity_sell_market(symbol, quantity)
            else:  # LIMIT
                if not price:
                    logger.error("Price required for limit orders")
                    return None
                    
                if instruction.upper() == "BUY":
                    order = equity_buy_limit(symbol, quantity, price)
                else:  # SELL
                    order = equity_sell_limit(symbol, quantity, price)
            
            # Add order duration (Day order by default)
            order.set_duration(Duration.DAY)
            order.set_session(Session.NORMAL)
            
            # Safety checks before placing order
            if instruction.upper() == "BUY":
                # Check if we have enough cash
                cash_balance = self.get_cash_balance(acc_hash)
                if cash_balance is None:
                    logger.error("Could not get cash balance")
                    return None
                
                estimated_cost = quantity * (price or 0)  # Rough estimate for market orders
                if cash_balance < estimated_cost + self.min_cash_buffer:
                    logger.error(f"Insufficient funds: ${cash_balance:.2f} available, need ${estimated_cost + self.min_cash_buffer:.2f}")
                    return None
            
            # Place the order
            logger.info(f"Placing {instruction} order for {quantity} shares of {symbol}")
            response = self.client.place_order(acc_hash, order)
            
            if response.status_code in [200, 201]:
                order_id = response.headers.get('Location', '').split('/')[-1]
                logger.info(f"Order placed successfully. Order ID: {order_id}")
                
                return {
                    "status": "success",
                    "order_id": order_id,
                    "symbol": symbol,
                    "quantity": quantity,
                    "instruction": instruction,
                    "order_type": order_type,
                    "price": price,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                logger.error(f"Failed to place order: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None
    
    def get_order_status(self, order_id: str, account_hash: Optional[str] = None) -> Optional[Dict]:
        """
        Get status of a specific order
        Args:
            order_id: Order ID to check
            account_hash: Account to query, defaults to configured account
        Returns: Order status or None if error
        """
        try:
            if not self.client:
                return None
            
            acc_hash = account_hash or self.account_hash
            if not acc_hash:
                logger.error("No account hash provided")
                return None
            
            response = self.client.get_order(acc_hash, order_id)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get order status: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return None
    
    def cancel_order(self, order_id: str, account_hash: Optional[str] = None) -> bool:
        """
        Cancel a specific order
        Args:
            order_id: Order ID to cancel
            account_hash: Account to use, defaults to configured account
        Returns: True if successfully cancelled, False otherwise
        """
        try:
            if not self.client:
                return False
            
            acc_hash = account_hash or self.account_hash
            if not acc_hash:
                logger.error("No account hash provided")
                return False
            
            response = self.client.cancel_order(acc_hash, order_id)
            
            if response.status_code == 200:
                logger.info(f"Order {order_id} cancelled successfully")
                return True
            else:
                logger.error(f"Failed to cancel order: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False

# Global instance
schwab_client = SchwabAPIClient()
