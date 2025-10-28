"""
Schwab API Client for D-AI-Trader
Handles authentication, order placement, and account data retrieval
"""

import os
import json
import logging
import time
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
import requests
SCHWAB_LIBRARY = None
easy_client = None
SchwabClient = None
SchwabAPI = None

try:
    from schwab.auth import easy_client as _easy_client
    from schwab.client.synchronous import Client as _SchwabClient
    easy_client = _easy_client
    SchwabClient = _SchwabClient
    SCHWAB_LIBRARY = "schwab"
except ImportError:
    try:
        from schwab_api import SchwabAPI as _LegacySchwab
        SchwabAPI = _LegacySchwab
        SCHWAB_LIBRARY = "schwab_api"
    except ImportError:
        SCHWAB_LIBRARY = None
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
from schwab.orders import equities as equity_orders
from schwab_ledger import (
    seed_from_balances,
    reconcile_from_rest,
    compute_effective_funds,
    components as ledger_components,
    get_ledger_state,
)

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
ACCESS_REFRESH_LEEWAY = 120  # seconds


def _build_basic_auth_header(client_id: str, client_secret: str) -> str:
    credentials = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return f"Basic {encoded}"


def _parse_iso8601(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _enrich_token_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    access_expires_in = int(data.get("expires_in", 0) or 0)
    refresh_token_ttl = int(data.get("refresh_token_expires_in", 0) or 0)
    data["fetched_at"] = now.isoformat()
    if access_expires_in:
        data["access_expires_at"] = (now + timedelta(seconds=access_expires_in)).isoformat()
    if refresh_token_ttl:
        data["refresh_expires_at"] = (now + timedelta(seconds=refresh_token_ttl)).isoformat()
    return data


def _load_token_bundle(token_path: Path) -> Optional[Dict[str, Any]]:
    if not token_path.exists():
        return None
    try:
        raw = json.loads(token_path.read_text())
        if isinstance(raw, dict):
            return raw
        return {"token": raw}
    except Exception as exc:
        logger.warning("Unable to parse Schwab token file %s: %s", token_path, exc)
        return None


def _extract_token_payload(bundle: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not bundle:
        return None
    token = bundle.get("token")
    if isinstance(token, dict):
        return token
    if isinstance(bundle, dict):
        return bundle
    return None


def _save_token_bundle(token_path: Path, token_payload: Dict[str, Any], creation_ts: Optional[int]) -> None:
    wrapped = {
        "creation_timestamp": creation_ts or int(time.time()),
        "token": token_payload,
    }
    token_path.write_text(json.dumps(wrapped, indent=2))
    logger.info(
        "Updated Schwab token file at %s (access expires %s)",
        token_path,
        token_payload.get("access_expires_at"),
    )


def _should_refresh_access(token: Dict[str, Any]) -> bool:
    expires_at = _parse_iso8601(token.get("access_expires_at"))
    if not expires_at:
        return True
    return datetime.now(timezone.utc) >= (expires_at - timedelta(seconds=ACCESS_REFRESH_LEEWAY))


def _refresh_token_lifespan_seconds(token: Dict[str, Any]) -> Optional[float]:
    refresh_expires_at = _parse_iso8601(token.get("refresh_expires_at"))
    if not refresh_expires_at:
        return None
    return (refresh_expires_at - datetime.now(timezone.utc)).total_seconds()

class SchwabAPIClient:
    """
    Schwab API client for trading operations
    """
    
    def __init__(self):
        """Initialize the Schwab client"""
        self.client: Optional[SchwabClient] = None
        self.account_hash = SCHWAB_ACCOUNT_HASH
        self.account_number: Optional[str] = None
        self.is_authenticated = False
        self.trading_mode = TRADING_MODE
        self.token_file = "schwab_tokens.json"
        self.token_path = self._resolve_token_path()
        
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

    def _resolve_token_path(self) -> Path:
        configured = os.getenv("SCHWAB_TOKEN_FILE")
        if configured:
            path = Path(configured)
        else:
            path = Path(os.path.dirname(__file__)) / self.token_file
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _maybe_refresh_tokens(self, token_path: Path) -> bool:
        bundle = _load_token_bundle(token_path)
        token = _extract_token_payload(bundle)
        if not token:
            return False

        if not _should_refresh_access(token):
            return False

        refresh_token = token.get("refresh_token")
        if not refresh_token:
            logger.warning("Schwab token file missing refresh_token; cannot refresh automatically.")
            return False

        try:
            headers = {
                "Authorization": _build_basic_auth_header(SCHWAB_CLIENT_ID, SCHWAB_CLIENT_SECRET),
                "Content-Type": "application/x-www-form-urlencoded",
            }
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
            response = requests.post(TOKEN_URL, headers=headers, data=payload, timeout=30)
            response.raise_for_status()
            refreshed = _enrich_token_payload(response.json())
            _save_token_bundle(token_path, refreshed, bundle.get("creation_timestamp") if bundle else None)
            logger.info("✅ Schwab access token refreshed automatically.")
            return True
        except Exception as exc:
            logger.error("Failed to refresh Schwab access token: %s", exc)
            return False

    def _access_token_expired(self, token_path: Path) -> bool:
        bundle = _load_token_bundle(token_path)
        token = _extract_token_payload(bundle)
        if not token:
            return False
        expires_at = _parse_iso8601(token.get("access_expires_at"))
        if not expires_at:
            return False
        return datetime.now(timezone.utc) >= expires_at

    def ensure_authenticated(self, force: bool = False) -> bool:
        token_path = self._resolve_token_path()
        refreshed = self._maybe_refresh_tokens(token_path)
        if refreshed or force or self._access_token_expired(token_path):
            self.client = None
            self.is_authenticated = False

        if not self.client or not self.is_authenticated:
            return self.authenticate()
        return True

    def authenticate(self) -> bool:
        """
        Authenticate with Schwab API using credentials
        Returns: True if authentication successful, False otherwise
        """
        try:
            if SCHWAB_LIBRARY is None:
                logger.error("Schwab API package not available. Install 'schwab' (preferred) or 'schwab-py'.")
                return False

            if not SCHWAB_CLIENT_ID or not SCHWAB_CLIENT_SECRET:
                logger.error("Schwab API credentials not configured")
                return False
            
            self.token_path = self._resolve_token_path()
            token_path = str(self.token_path)
            token_bundle = _load_token_bundle(self.token_path)
            token_payload = _extract_token_payload(token_bundle)
            refreshed = self._maybe_refresh_tokens(self.token_path)
            if refreshed:
                token_bundle = _load_token_bundle(self.token_path)
                token_payload = _extract_token_payload(token_bundle)
            if token_payload:
                remaining_refresh = _refresh_token_lifespan_seconds(token_payload)
                if remaining_refresh is not None and remaining_refresh < 24 * 3600:
                    logger.warning(
                        "Schwab refresh token expires in %.2f hours. Re-run schwab_manual_auth.py to renew.",
                        remaining_refresh / 3600.0,
                    )

            interactive = os.getenv("DAI_SCHWAB_INTERACTIVE", "true").lower() not in {"0", "false", "no"}
            manual_flow = os.getenv("DAI_SCHWAB_MANUAL_FLOW", "0").lower() in {"1", "true", "yes"}

            if SCHWAB_LIBRARY == "schwab":
                logger.info("Authenticating with Schwab API (schwab) using token file %s", token_path)
                if manual_flow:
                    from schwab.auth import client_from_manual_flow
                    client = client_from_manual_flow(
                        api_key=SCHWAB_CLIENT_ID,
                        app_secret=SCHWAB_CLIENT_SECRET,
                        redirect_uri=SCHWAB_REDIRECT_URI,
                        token_path=token_path,
                        enforce_enums=True,
                    )
                else:
                    client = easy_client(
                        api_key=SCHWAB_CLIENT_ID,
                        app_secret=SCHWAB_CLIENT_SECRET,
                        callback_url=SCHWAB_REDIRECT_URI,
                        token_path=token_path,
                        enforce_enums=True,
                        interactive=interactive,
                    )

                if isinstance(client, SchwabClient):
                    self.client = client
                    self.is_authenticated = True
                    logger.info("Schwab client authenticated successfully")
                    self._refresh_account_mapping()
                    if self.account_hash:
                        print(f"✅ Schwab authentication complete for hash {self.account_hash}")
                    return True

                logger.error("Unexpected client type returned from easy_client: %s", type(client))
                return False

            if SCHWAB_LIBRARY == "schwab_api":
                logger.warning("Using deprecated 'schwab_api' client. Consider upgrading to the official 'schwab' package.")
                try:
                    self.client = SchwabAPI(
                        client_id=SCHWAB_CLIENT_ID,
                        client_secret=SCHWAB_CLIENT_SECRET,
                        redirect_uri=SCHWAB_REDIRECT_URI,
                        token_path=token_path,
                    )
                    self.is_authenticated = True
                    logger.info("Legacy schwab_api client initialized successfully")
                    self._refresh_account_mapping()
                    if self.account_hash:
                        print(f"✅ Schwab authentication complete for hash {self.account_hash}")
                    return True
                except Exception as legacy_error:
                    logger.error(f"Legacy schwab_api authentication failed: {legacy_error}")
                    return False

            logger.error("Unsupported Schwab client library configuration")
            return False
                
        except Exception as e:
            logger.error(f"Schwab authentication error: {e}")
            return False

    def _refresh_account_mapping(self) -> None:
        """
        Map configured account hash to Schwab account number for downstream APIs (streaming, etc.)
        """
        if not self.client or not self.account_hash:
            return
        try:
            response = self.client.get_account_numbers()
            if response.status_code != 200:
                logger.warning("Unable to fetch Schwab account numbers (status=%s)", response.status_code)
                return
            data = response.json() or []
            for entry in data:
                if entry.get("hashValue") == self.account_hash:
                    self.account_number = entry.get("accountNumber")
                    logger.info("Mapped Schwab account hash %s to number %s", self.account_hash, self.account_number)
                    print(f"✅ Schwab account mapping: hash={self.account_hash} number={self.account_number}")
                    break
            else:
                logger.warning("Configured Schwab account hash %s not found in account numbers list", self.account_hash)
        except Exception as exc:
            logger.error(f"Error refreshing Schwab account mapping: {exc}")
    
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
                fields=[self.client.Account.Fields.POSITIONS]
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
            available_funds = _extract_available_funds(current_balances) or 0.0
            return float(available_funds)
            
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
            if (self.trading_mode or "").lower() not in {"live", "real_world"}:
                logger.warning(f"Trading mode is '{self.trading_mode}' - skipping real order placement")
                return {
                    "status": "skipped",
                    "reason": f"Trading mode is {self.trading_mode}, not live",
                    "symbol": symbol,
                    "quantity": quantity,
                    "instruction": instruction
                }
            
            order = self._build_equity_order(symbol, quantity, instruction, order_type, price)
            if order is None:
                return None
            
            # Safety checks before placing order
            if instruction.upper() == "BUY":
                # Check if we have enough cash when balance info available
                cash_balance = self.get_cash_balance(acc_hash)
                if cash_balance is None:
                    logger.warning("Could not retrieve cash balance; proceeding without pre-check")
                else:
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
                status_info = self._post_submit_order_check(acc_hash, order_id)
                if status_info and status_info["status"] in {"REJECTED", "CANCELED"}:
                    logger.error("Schwab order %s %s: %s", order_id, status_info["status"], status_info.get("reason"))
                    return {
                        "status": status_info["status"].lower(),
                        "order_id": order_id,
                        "symbol": symbol,
                        "quantity": quantity,
                        "instruction": instruction,
                        "order_type": order_type,
                        "price": price,
                        "timestamp": datetime.now().isoformat(),
                        "reason": status_info.get("reason"),
                        "success": False,
                    }

                return {
                    "status": "success",
                    "order_id": order_id,
                    "symbol": symbol,
                    "quantity": quantity,
                    "instruction": instruction,
                    "order_type": order_type,
                    "price": price,
                    "timestamp": datetime.now().isoformat(),
                    "order_status": status_info,
                    "success": True,
                }
            else:
                logger.error(f"Failed to place order: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    def _build_equity_order(self, symbol: str, quantity: int, instruction: str,
                            order_type: str, price: Optional[float]):
        try:
            order_type_upper = (order_type or "").upper()
            instruction_upper = (instruction or "").upper()

            if order_type_upper == "MARKET":
                if instruction_upper == "BUY":
                    order = equity_orders.equity_buy_market(symbol, quantity)
                elif instruction_upper == "SELL":
                    order = equity_orders.equity_sell_market(symbol, quantity)
                elif instruction_upper == "SELL_SHORT":
                    order = equity_orders.equity_sell_short_market(symbol, quantity)
                elif instruction_upper == "BUY_TO_COVER":
                    order = equity_orders.equity_buy_to_cover_market(symbol, quantity)
                else:
                    logger.error(f"Unsupported market instruction: {instruction_upper}")
                    return None
            elif order_type_upper == "LIMIT":
                if price is None:
                    logger.error("Price required for limit orders")
                    return None
                if instruction_upper == "BUY":
                    order = equity_orders.equity_buy_limit(symbol, quantity, price)
                elif instruction_upper == "SELL":
                    order = equity_orders.equity_sell_limit(symbol, quantity, price)
                elif instruction_upper == "SELL_SHORT":
                    order = equity_orders.equity_sell_short_limit(symbol, quantity, price)
                elif instruction_upper == "BUY_TO_COVER":
                    order = equity_orders.equity_buy_to_cover_limit(symbol, quantity, price)
                else:
                    logger.error(f"Unsupported limit instruction: {instruction_upper}")
                    return None
            else:
                logger.error(f"Unsupported order type: {order_type}")
                return None

            try:
                order.set_duration(equity_orders.Duration.DAY)
                order.set_session(equity_orders.Session.NORMAL)
            except Exception:
                logger.debug("Equity order builder does not support duration/session setters; relying on defaults")
            return order
        except Exception as exc:
            logger.error(f"Failed to build Schwab order: {exc}")
            return None

    def _post_submit_order_check(self, account_hash: str, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Poll Schwab for the submitted order's status and surface any rejection reason.
        """
        if not self.client or not order_id:
            return None

        try:
            time.sleep(1.0)
            response = self.client.get_order(account_hash, order_id)
            if response.status_code != 200:
                logger.debug("Unable to retrieve Schwab order %s status (status=%s)", order_id, response.status_code)
                return None

            data = response.json() or {}
            status = (data.get("status") or "").upper()
            cancel_time = data.get("cancelTime") or data.get("orderCancelTime")
            cancel_reason = None
            if "orderLegCollection" in data:
                for leg in data.get("orderLegCollection") or []:
                    cancel_reason = cancel_reason or leg.get("cancelReason")
                    if cancel_reason:
                        break
            cancel_reason = cancel_reason or data.get("cancelationReason") or data.get("cancelledReason")

            return {
                "status": status,
                "reason": cancel_reason,
                "cancel_time": cancel_time,
                "raw": data,
            }
        except Exception as exc:
            logger.debug("Exception while fetching Schwab order status: %s", exc)
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

def _first_non_none(payload: Dict[str, Any], candidates: List[str], default: float = 0.0) -> float:
    """
    Return the first present float-compatible value for the provided keys.
    """
    for key in candidates:
        if key in payload and payload[key] is not None:
            try:
                return float(payload[key])
            except (TypeError, ValueError):
                logger.debug("Unable to parse Schwab balance field %s=%r", key, payload[key])
    return float(default)

def format_position_row(position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convert raw Schwab position into normalized structure used by dashboard.
    """
    instrument = position.get("instrument", {}) or {}
    symbol = instrument.get("symbol")
    if not symbol:
        return None

    asset_type = _normalize_asset_type(instrument)
    long_qty = float(position.get("longQuantity") or 0)
    short_qty = float(position.get("shortQuantity") or 0)
    qty = long_qty - short_qty
    if abs(qty) < 1e-9:
        return None

    market_value = float(position.get("marketValue") or 0)
    avg_price = float(position.get("averagePrice") or position.get("averageLongPrice") or 0)
    current_price = market_value / qty if qty else 0
    gain_loss = float(position.get("longOpenProfitLoss") or (market_value - (avg_price * qty)))
    gain_loss_pct = (gain_loss / (avg_price * qty) * 100) if avg_price and qty else 0
    return {
        "symbol": symbol,
        "shares": qty,
        "average_price": avg_price,
        "current_price": current_price,
        "market_value": market_value,
        "gain_loss": gain_loss,
        "gain_loss_percentage": gain_loss_pct,
        "asset_type": asset_type,
        "total_value": avg_price * qty if avg_price else market_value,
        "raw": position,
    }

def _normalize_asset_type(instrument: Dict[str, Any]) -> str:
    """
    Normalize Schwab instrument asset types so ETFs marked as COLLECTIVE_INVESTMENT are recognized.
    """
    asset_type = (instrument.get("assetType") or "").upper()
    instrument_type = (instrument.get("type") or asset_type).upper()

    if instrument_type == "EXCHANGE_TRADED_FUND":
        return "ETF"

    if asset_type in {"EQUITY", "ETF", "ETN", "MUTUAL_FUND"}:
        return asset_type

    if asset_type == "COLLECTIVE_INVESTMENT":
        return "ETF" if instrument_type == "EXCHANGE_TRADED_FUND" else "COLLECTIVE_INVESTMENT"

    return asset_type or instrument_type or "UNKNOWN"

def _format_settled_position(formatted_real: Optional[Dict[str, Any]], position: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Build a settled-position snapshot based on Schwab totals.
    """
    instrument = position.get("instrument", {}) or {}
    symbol = instrument.get("symbol")
    if not symbol:
        return None

    asset_type = _normalize_asset_type(instrument)
    settled_qty = float(position.get("settledLongQuantity") or 0) - float(position.get("settledShortQuantity") or 0)
    if abs(settled_qty) < 1e-9:
        return None

    avg_price = float(position.get("averagePrice") or position.get("averageLongPrice") or 0)
    current_price = formatted_real.get("current_price", 0.0) if formatted_real else 0.0
    if current_price == 0:
        market_value_total = float(position.get("marketValue") or 0)
        total_qty = float(position.get("longQuantity") or 0) - float(position.get("shortQuantity") or 0)
        current_price = market_value_total / total_qty if total_qty else avg_price

    market_value = current_price * settled_qty
    return {
        "symbol": symbol,
        "shares": settled_qty,
        "average_price": avg_price,
        "current_price": current_price,
        "market_value": market_value,
        "asset_type": asset_type,
    }

OPEN_ORDER_STATUSES = {
    "WORKING",
    "QUEUED",
    "PENDING_ACTIVATION",
    "PENDING_CANCEL",
    "PENDING_REPLACE",
    "ACCEPTED",
    "AWAITING_PARENT_ORDER",
}

def _fetch_transactions_today(client: SchwabClient, account_hash: str) -> List[Dict[str, Any]]:
    """
    Retrieve Schwab transactions covering the last 24 hours to identify unsettled activity.
    """
    try:
        now_utc = datetime.now(timezone.utc)
        start = now_utc - timedelta(days=1)
        response = client.get_transactions(account_hash, start_date=start, end_date=now_utc)
        if response.status_code != 200:
            logger.debug("Unable to fetch Schwab transactions (status=%s)", response.status_code)
            return []
        data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("transactions", [])
        return []
    except Exception as exc:
        logger.debug("Error fetching Schwab transactions: %s", exc)
        return []

def _derive_effective_funds_available(securities_account: Dict[str, Any],
                                      transactions_today: Optional[List[Dict[str, Any]]] = None) -> Dict[str, float]:
    """
    Approximate funds immediately available for trading by combining Schwab fields
    and same-day unsettled activity.
    """
    cb = securities_account.get("currentBalances", {}) or {}
    ib = securities_account.get("initialBalances", {}) or {}
    pb = securities_account.get("projectedBalances", {}) or {}

    explicit_candidates = [
        _first_non_none(cb, [
            "cashAvailableForTrading",
            "cashAvailableForWithdrawal",
            "availableFundsForTrading",
            "availableFunds",
            "cashReceipts",
            "cashBalance",
        ], 0.0),
        _first_non_none(pb, ["cashAvailableForTrading", "availableFundsForTrading"], 0.0),
        _first_non_none(ib, ["cashAvailableForTrading", "availableFundsForTrading"], 0.0),
    ]

    explicit = 0.0
    for candidate in explicit_candidates:
        if candidate and candidate > 0:
            explicit = candidate
            break
    if explicit <= 0:
        explicit = _first_non_none(cb, ["cashBalance", "totalCash"], 0.0)

    derived_cash = (
        _first_non_none(cb, ["totalCash"])
        + _first_non_none(cb, ["moneyMarketFund"])
        + _first_non_none(cb, ["cashReceipts"])
        + _first_non_none(cb, ["unsettledCash"])
        - _first_non_none(cb, ["cashCall", "cashDebitCallValue"])
    )

    effective = max(explicit, derived_cash)
    same_day_net = 0.0

    if transactions_today:
        try:
            today = datetime.now(timezone.utc).date()
            credit = debit = 0.0

            for tx in transactions_today:
                if (tx.get("type") or "").upper() != "TRADE":
                    continue

                instruction = (tx.get("transactionItem", {}).get("instruction") or tx.get("instruction") or "").upper()
                raw_amount = tx.get("amount")
                if raw_amount is None:
                    raw_amount = tx.get("netAmount") or tx.get("price")

                try:
                    amount = float(raw_amount or 0.0)
                except Exception:
                    amount = 0.0

                settlement = tx.get("settlementDate") or tx.get("settlementDateTime")
                unsettled = True
                if settlement:
                    try:
                        settle_dt = datetime.fromisoformat(str(settlement).replace("Z", "+00:00"))
                        if isinstance(settle_dt, datetime):
                            settle_date = settle_dt.date()
                        else:
                            settle_date = settle_dt
                        unsettled = settle_date > today
                    except Exception:
                        pass

                if not unsettled:
                    continue

                if instruction in {"SELL", "SELL_SHORT"}:
                    credit += abs(amount)
                elif instruction in {"BUY", "BUY_TO_COVER", "BUY_TO_OPEN", "BUY_TO_CLOSE"}:
                    debit += abs(amount)

            same_day_net = credit - debit
            effective = max(effective, same_day_net + _first_non_none(cb, ["totalCash"]))
        except Exception as exc:
            logger.debug("Failed processing Schwab transactions for funds availability: %s", exc)

    effective = max(0.0, effective)
    return {
        "effective": round(effective, 2),
        "explicit": round(max(0.0, explicit), 2),
        "derived_cash": round(max(0.0, derived_cash), 2),
        "same_day_net": round(same_day_net, 2),
    }

def _extract_available_funds(balances: Dict[str, Any]) -> Optional[float]:
    """
    Prefer Schwab's 'funds available' style balances when present.
    Falls back to cash balances when the preferred fields are missing.
    """
    candidate_keys = [
        "fundsAvailableForTrading",
        "cashAvailableForTrading",
        "cashAvailableForTradingSettledCash",
        "cashAvailableForWithdrawal",
        "availableFundsForTrading",
        "availableFunds",
        "buyingPower",
        "dayTradingBuyingPower",
        "cashReceipts",
        "cashBalance",
    ]
    for key in candidate_keys:
        value = balances.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.debug("Unable to parse Schwab balance field %s=%r", key, value)
    return None

def get_portfolio_snapshot() -> Optional[Dict[str, Any]]:
    """
    Retrieve balances and positions from Schwab and normalize for downstream use.
    """
    if not schwab_client.ensure_authenticated():
        logger.error("Unable to authenticate Schwab client; portfolio snapshot unavailable")
        return None
    if not schwab_client.client or not schwab_client.account_hash:
        logger.warning("Schwab client not ready; cannot fetch portfolio snapshot")
        return None

    try:
        response = schwab_client.client.get_account(
            schwab_client.account_hash,
            fields=[schwab_client.client.Account.Fields.POSITIONS],
        )
        if response.status_code != 200:
            logger.error("Failed to fetch Schwab account snapshot (status=%s)", response.status_code)
            return None

        payload = response.json()
        print(f"📡 Schwab API response for hash={schwab_client.account_hash} status={response.status_code}")
        print(json.dumps(payload, indent=2))

        securities_account = payload.get("securitiesAccount", {}) or {}
        balances = securities_account.get("currentBalances", {}) or {}
        positions_raw = securities_account.get("positions", []) or []

        seed_from_balances(balances)

        formatted_positions: List[Dict[str, Any]] = []
        settled_positions: List[Dict[str, Any]] = []
        for position in positions_raw:
            formatted = format_position_row(position)
            if formatted:
                formatted_positions.append(formatted)
            settled_formatted = _format_settled_position(formatted, position)
            if settled_formatted:
                settled_positions.append(settled_formatted)

        cash_balance_settled = _first_non_none(balances, [
            "cashBalance",
            "totalCash",
        ])
        unsettled_cash = _first_non_none(balances, ["unsettledCash"], 0.0)
        funds_available_raw = _extract_available_funds(balances) or 0.0

        transactions_today: Optional[List[Dict[str, Any]]] = None
        if schwab_client.client and schwab_client.account_hash:
            try:
                transactions = _fetch_transactions_today(schwab_client.client, schwab_client.account_hash)
                if transactions:
                    transactions_today = transactions
            except Exception as exc:
                logger.debug("Unable to retrieve Schwab transactions: %s", exc)

        open_orders_sample: List[Dict[str, Any]] = []
        total_open_orders = 0
        orders_payload: List[Dict[str, Any]] = []
        if schwab_client.client and schwab_client.account_hash:
            try:
                orders_response = schwab_client.client.get_orders_for_account(schwab_client.account_hash)
                if hasattr(orders_response, "json"):
                    orders_payload = orders_response.json()
                else:
                    orders_payload = orders_response
            except Exception as exc:
                logger.debug("Unable to fetch Schwab open orders: %s", exc)
                orders_payload = []

        if isinstance(orders_payload, dict):
            orders_payload = orders_payload.get("orders") or []

        for order in orders_payload or []:
            status = (order.get("status") or "").upper()
            if status in OPEN_ORDER_STATUSES:
                total_open_orders += 1
                if len(open_orders_sample) < 5:
                    open_orders_sample.append(order)

        reconcile_from_rest(orders_payload, transactions_today)
        funds_info = _derive_effective_funds_available(
            securities_account,
            transactions_today=transactions_today
        )

        buying_power = _first_non_none(balances, ["buyingPower"], funds_info.get("effective", funds_available_raw))
        day_trading_power = _first_non_none(balances, ["dayTradingBuyingPower"], 0.0)
        account_value = _first_non_none(balances, ["longMarketValue", "liquidationValue"], 0.0)
        total_value = sum(p.get("market_value", 0) for p in formatted_positions)
        if account_value == 0 and total_value:
            account_value = total_value

        baseline_funds = funds_info.get("explicit", funds_available_raw) or funds_available_raw
        effective_with_ledger = compute_effective_funds(baseline_funds)
        ledger_comp = ledger_components()
        open_order_reserve = ledger_comp.get("open_buy_reserve", 0.0)

        funds_info["effective"] = effective_with_ledger

        account_info_payload = {
            "account_value": float(account_value),
            "buying_power": float(buying_power),
            "day_trading_buying_power": float(day_trading_power),
            "funds_available_for_trading": effective_with_ledger,
            "funds_available_explicit": funds_info.get("explicit", funds_available_raw),
            "funds_available_derived": funds_info.get("derived_cash", funds_available_raw),
            "same_day_net_activity": funds_info.get("same_day_net", 0.0),
            "cash_balance": float(cash_balance_settled),
            "unsettled_cash": float(unsettled_cash),
            "order_reserve": float(open_order_reserve),
            "open_orders_count": total_open_orders,
            "balances_raw": balances,
            "positions_raw": positions_raw,
            "account_hash": schwab_client.account_hash,
            "account_number": schwab_client.account_number,
            "account_type": securities_account.get("type"),
            "ledger_components": ledger_comp,
        }

        return {
            "balances_raw": balances,
            "positions_raw": positions_raw,
            "positions": formatted_positions,
            "settled_positions": settled_positions,
            "cash_balance": float(cash_balance_settled),
            "cash_balance_settled": float(cash_balance_settled),
            "unsettled_cash": float(unsettled_cash),
            "funds_available_raw": float(funds_available_raw),
            "funds_available_explicit": funds_info.get("explicit", funds_available_raw),
            "funds_available_derived": funds_info.get("derived_cash", funds_available_raw),
            "funds_available_effective": effective_with_ledger,
            "same_day_net_activity": funds_info.get("same_day_net", 0.0),
            "order_reserve": float(open_order_reserve),
            "buying_power": float(buying_power),
            "day_trading_power": float(day_trading_power),
            "account_value": float(account_value),
            "account_number": schwab_client.account_number,
            "account_hash": schwab_client.account_hash,
            "account_type": securities_account.get("type"),
            "aggregated_balance": payload.get("aggregatedBalance"),
            "transactions_sample": (transactions_today[:5] if transactions_today else None),
            "open_orders_sample": open_orders_sample,
            "open_orders_count": total_open_orders,
            "ledger_state": get_ledger_state(),
            "ledger_components": ledger_comp,
            "account_info": account_info_payload,
        }
    except Exception as exc:
        logger.error(f"Error fetching Schwab portfolio snapshot: {exc}")
        return None
