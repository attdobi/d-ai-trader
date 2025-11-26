"""
Decision Validator - Prevents AI hallucinations and invalid trades

FINANCIAL GUARDRAILS:
- Can only sell stocks you actually own
- Cannot buy stocks you already own (must sell first)
- Amounts must be within valid ranges
- All required fields must be present
- Tickers must be valid symbols

This is critical for real-money trading - no AI hallucinations allowed!
"""

import os
import re
from typing import List, Dict, Any, Tuple

MIN_BUY_AMOUNT = float(os.getenv("DAI_MIN_BUY_AMOUNT", "1000"))
MAX_BUY_AMOUNT = float(os.getenv("DAI_MAX_BUY_AMOUNT", "4000"))

class DecisionValidator:
    """Validates trading decisions to prevent hallucinations and errors"""
    
    def __init__(self, current_holdings: List[Dict], available_cash: float, allow_sell_reuse: bool = True):
        """
        Initialize validator with current portfolio state
        
        Args:
            current_holdings: List of current holdings (excluding CASH)
            available_cash: Available cash balance
            allow_sell_reuse: Whether sell proceeds can be reused immediately
        """
        self.current_tickers = set(h['ticker'].upper() for h in current_holdings if h['ticker'] != 'CASH')
        self.holdings_map = {h['ticker'].upper(): h for h in current_holdings if h['ticker'] != 'CASH'}
        self.available_cash = available_cash
        self.allow_sell_reuse = allow_sell_reuse
        
        print(f"🛡️  Decision Validator Initialized:")
        print(f"   Current Holdings: {', '.join(sorted(self.current_tickers)) if self.current_tickers else 'NONE'}")
        print(f"   Available Cash: ${available_cash:.2f}")
        if not allow_sell_reuse:
            print("   ⚠️  Cash account guardrail: Sell proceeds remain unsettled until next cycle.")
    
    def validate_decisions(self, decisions: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Validate all decisions and separate valid from invalid
        
        Returns:
            (valid_decisions, invalid_decisions_with_reasons)
        """
        valid = []
        invalid = []
        
        for i, decision in enumerate(decisions, 1):
            is_valid, reason = self._validate_single_decision(decision, i)
            
            if is_valid:
                valid.append(decision)
                print(f"   ✅ Decision {i}: {decision.get('action', 'N/A').upper()} {decision.get('ticker', 'N/A')}")
                self._apply_decision_effects(decision)
            else:
                invalid.append({
                    'decision': decision,
                    'validation_error': reason
                })
                print(f"   ❌ Decision {i} REJECTED: {reason}")
        
        print(f"🛡️  Validation Complete: {len(valid)} valid, {len(invalid)} rejected")
        return valid, invalid
    
    def _validate_single_decision(self, decision: Dict, index: int) -> Tuple[bool, str]:
        """
        Validate a single decision
        
        Returns:
            (is_valid, error_reason)
        """
        # Rule 1: Must be a dict
        if not isinstance(decision, dict):
            return False, f"Not a dict: {type(decision)}"
        
        # Rule 2: Must have required fields
        action = decision.get('action', '').lower()
        ticker_raw = decision.get('ticker', '')
        ticker = self._normalize_ticker(ticker_raw)
        amount_usd = decision.get('amount_usd', 0)
        reason = decision.get('reason', '')
        
        if not action:
            return False, "Missing 'action' field"
        if not ticker:
            return False, "Missing 'ticker' field"

        # Mutate decision with normalized ticker so downstream consumers use cleaned symbol
        decision['ticker'] = ticker
        if not reason:
            return False, "Missing 'reason' field"
        
        # Rule 3: Action must be valid
        if action not in ['buy', 'sell', 'hold']:
            return False, f"Invalid action '{action}' (must be buy/sell/hold)"
        
        # Rule 4: Ticker must be valid format (1-5 uppercase letters)
        if not ticker.isalpha() or len(ticker) > 5:
            return False, f"Invalid ticker format: '{ticker}'"
        
        # Rule 5: SELL validation - can only sell stocks you own
        if action == 'sell':
            if ticker not in self.current_tickers:
                return False, f"AI HALLUCINATION: Cannot sell {ticker} - you don't own it! (Holdings: {', '.join(sorted(self.current_tickers)) if self.current_tickers else 'NONE'})"
        
        # Rule 6: BUY validation - cannot buy stocks you already own
        if action == 'buy':
            if ticker in self.current_tickers:
                return False, f"Cannot buy {ticker} - you already own it! Must SELL first before re-buying"
            
            # Rule 7: Amount validation for buys
            try:
                amount = float(amount_usd)
                if amount < MIN_BUY_AMOUNT:
                    return False, f"Buy amount ${amount:.2f} too small (minimum ${MIN_BUY_AMOUNT:,.0f})"
                if amount > MAX_BUY_AMOUNT:
                    return False, f"Buy amount ${amount:.2f} too large (maximum ${MAX_BUY_AMOUNT:,.0f})"
                if amount > self.available_cash:
                    return False, f"Buy amount ${amount:.2f} exceeds available cash ${self.available_cash:.2f}"
            except (ValueError, TypeError):
                return False, f"Invalid amount_usd: {amount_usd}"
        
        # Rule 8: HOLD validation - can only hold stocks you own
        if action == 'hold':
            if ticker not in self.current_tickers:
                return False, f"AI HALLUCINATION: Cannot hold {ticker} - you don't own it! (Holdings: {', '.join(sorted(self.current_tickers)) if self.current_tickers else 'NONE'})"
        
        # All validation passed
        return True, ""

    def _normalize_ticker(self, ticker: Any) -> str:
        if not isinstance(ticker, str):
            return ''
        cleaned = ticker.strip().upper()
        if not cleaned:
            return ''
        # Strip ranking prefixes like R1-KVUE, r2/TSLA, etc.
        match = re.match(r'^R(\d+)\s*[-_:/\\\s]+([A-Z0-9.]+)$', cleaned)
        if match:
            cleaned = match.group(2)
        return cleaned
    
    def _apply_decision_effects(self, decision: Dict) -> None:
        """
        Update internal cash/holdings state after accepting a decision so
        subsequent validations reflect freed cash or new positions.
        """
        action = decision.get('action', '').lower()
        ticker = decision.get('ticker', '').upper().strip()
        
        if action == 'sell':
            holding = self.holdings_map.get(ticker, {})
            proceeds = (
                holding.get('current_value')
                or holding.get('total_value')
                or (holding.get('current_price', 0) * holding.get('shares', 0))
                or 0
            )
            if self.allow_sell_reuse:
                self.available_cash += proceeds
                print(f"      ➕ Cash after SELL {ticker}: ${self.available_cash:.2f}")
            else:
                print(f"      ⌛ SELL {ticker} proceeds pending settlement (${proceeds:.2f}); cash stays ${self.available_cash:.2f}")
            self.current_tickers.discard(ticker)
            self.holdings_map.pop(ticker, None)
        elif action == 'buy':
            try:
                amount = float(decision.get('amount_usd', 0))
            except (ValueError, TypeError):
                amount = 0
            self.available_cash -= amount
            self.current_tickers.add(ticker)
            self.holdings_map[ticker] = {"ticker": ticker}
            print(f"      ➖ Cash after BUY {ticker}: ${self.available_cash:.2f}")
    
    def get_missing_holdings_decisions(self, decisions: List[Dict]) -> List[str]:
        """
        Check if AI provided decisions for ALL current holdings
        
        Returns:
            List of tickers that were not analyzed (AI should have provided sell/hold)
        """
        decision_tickers = set(d.get('ticker', '').upper() for d in decisions if isinstance(d, dict))
        missing = self.current_tickers - decision_tickers
        
        if missing:
            print(f"⚠️  AI FAILED to analyze these holdings: {', '.join(sorted(missing))}")
            print(f"   AI should have provided SELL or HOLD decision for each!")
        
        return list(missing)
