"""Stock paper trading execution gateway.

Simulates US stock trading with real market prices from YFinance.
Supports market hours enforcement and realistic fee/slippage modeling.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import List, Optional

import pytz
from loguru import logger

from valuecell.agents.common.trading.models import (
    FeatureVector,
    TradeInstruction,
    TradeSide,
    TxResult,
    TxStatus,
    derive_side_from_action,
)
from valuecell.agents.common.trading.utils import extract_price_map

from .interfaces import BaseExecutionGateway


def is_us_market_open() -> bool:
    """Check if US stock market is currently open.

    US market hours: 9:30 AM - 4:00 PM Eastern Time, Monday-Friday.
    Does not account for holidays.

    Returns:
        True if market is open, False otherwise
    """
    eastern = pytz.timezone("US/Eastern")
    now = datetime.now(eastern)

    # Weekend check (Saturday=5, Sunday=6)
    if now.weekday() >= 5:
        return False

    # Market hours: 9:30 - 16:00 ET
    market_open = time(9, 30)
    market_close = time(16, 0)

    current_time = now.time()
    return market_open <= current_time <= market_close


class StockPaperExecutionGateway(BaseExecutionGateway):
    """Paper trading gateway for US stocks using YFinance prices.

    Features:
    - Real-time price fetching from Yahoo Finance (15-min delayed)
    - Market hours enforcement (optional)
    - Configurable slippage and fee models
    - Per-share and percentage-based fees

    Note: This gateway does NOT track positions or cash internally.
    Position/cash management is handled by the PortfolioService.
    """

    def __init__(
        self,
        fee_bps: float = 10.0,
        fee_per_share: float = 0.0,
        slippage_bps: float = 10.0,
        enforce_market_hours: bool = True,
    ) -> None:
        """Initialize stock paper trading gateway.

        Args:
            fee_bps: Trading fee in basis points (default 10 bps = 0.1%)
            fee_per_share: Additional per-share fee (default 0)
            slippage_bps: Simulated slippage in basis points (default 10 bps)
            enforce_market_hours: If True, reject orders outside market hours
        """
        self._fee_bps = float(fee_bps)
        self._fee_per_share = float(fee_per_share)
        self._slippage_bps = float(slippage_bps)
        self._enforce_market_hours = enforce_market_hours
        self.executed: List[TradeInstruction] = []

    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """Fetch current price for a stock symbol from YFinance.

        Args:
            symbol: Stock symbol (e.g., 'AAPL', 'TSLA')

        Returns:
            Current price or None if unavailable
        """
        try:
            import yfinance as yf

            # Normalize symbol (remove any suffix like -USD)
            normalized = symbol.split("-")[0].upper() if "-" in symbol else symbol.upper()

            ticker = yf.Ticker(normalized)

            # Run synchronous yfinance call in executor
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                lambda: ticker.history(period="1d", interval="1m"),
            )

            if data is not None and not data.empty:
                return float(data.iloc[-1]["Close"])

            # Fallback to fast_info
            fast_info = await loop.run_in_executor(
                None,
                lambda: getattr(ticker, "fast_info", None),
            )
            if fast_info:
                price = (
                    fast_info.get("last_price")
                    or fast_info.get("regular_market_price")
                    or fast_info.get("last_close")
                )
                if price:
                    return float(price)

            return None

        except Exception as e:
            logger.warning(f"Failed to fetch price for {symbol}: {e}")
            return None

    async def execute(
        self,
        instructions: List[TradeInstruction],
        market_features: Optional[List[FeatureVector]] = None,
    ) -> List[TxResult]:
        """Execute trade instructions with simulated fills.

        For each instruction:
        1. Check market hours (if enforced)
        2. Fetch current price from YFinance (or use market_features)
        3. Apply slippage based on trade direction
        4. Calculate fees
        5. Return execution result

        Args:
            instructions: List of trade instructions to execute
            market_features: Optional market features for price fallback

        Returns:
            List of transaction results
        """
        if not instructions:
            return []

        results: List[TxResult] = []

        # Extract price map from market features as fallback
        price_map = extract_price_map(market_features or [])

        for inst in instructions:
            self.executed.append(inst)
            symbol = inst.instrument.symbol

            # Determine side
            side = (
                getattr(inst, "side", None)
                or derive_side_from_action(getattr(inst, "action", None))
                or TradeSide.BUY
            )

            # Check market hours
            if self._enforce_market_hours and not is_us_market_open():
                logger.info(f"Market closed, rejecting order for {symbol}")
                results.append(
                    TxResult(
                        instruction_id=inst.instruction_id,
                        instrument=inst.instrument,
                        side=side,
                        requested_qty=float(inst.quantity),
                        filled_qty=0.0,
                        status=TxStatus.REJECTED,
                        reason="market_closed",
                        meta=inst.meta,
                    )
                )
                continue

            # Get current price
            ref_price = await self._get_current_price(symbol)

            # Fallback to market features if YFinance fails
            if ref_price is None or ref_price <= 0:
                ref_price = float(price_map.get(symbol, 0.0) or 0.0)

            if ref_price is None or ref_price <= 0:
                logger.warning(f"No price available for {symbol}, rejecting order")
                results.append(
                    TxResult(
                        instruction_id=inst.instruction_id,
                        instrument=inst.instrument,
                        side=side,
                        requested_qty=float(inst.quantity),
                        filled_qty=0.0,
                        status=TxStatus.REJECTED,
                        reason="no_price_data",
                        meta=inst.meta,
                    )
                )
                continue

            # Apply slippage
            slip_bps = float(inst.max_slippage_bps or self._slippage_bps)
            slip = slip_bps / 10_000.0

            if side == TradeSide.BUY:
                exec_price = ref_price * (1.0 + slip)
            else:
                exec_price = ref_price * (1.0 - slip)

            # Calculate fees
            qty = float(inst.quantity)
            notional = exec_price * qty
            fee_cost = (
                notional * (self._fee_bps / 10_000.0)  # Percentage fee
                + qty * self._fee_per_share  # Per-share fee
            )

            logger.debug(
                f"Stock paper trade: {side.value} {qty} {symbol} @ {exec_price:.2f}, "
                f"fee={fee_cost:.4f}, slippage={slip_bps}bps"
            )

            results.append(
                TxResult(
                    instruction_id=inst.instruction_id,
                    instrument=inst.instrument,
                    side=side,
                    requested_qty=qty,
                    filled_qty=qty,
                    avg_exec_price=float(exec_price),
                    slippage_bps=slip_bps if slip_bps > 0 else None,
                    fee_cost=fee_cost if fee_cost > 0 else None,
                    leverage=inst.leverage,
                    status=TxStatus.FILLED,
                    meta=inst.meta,
                )
            )

        return results

    async def test_connection(self) -> bool:
        """Test connection to YFinance.

        Attempts to fetch price for a known symbol (AAPL).

        Returns:
            True if connection is successful
        """
        try:
            price = await self._get_current_price("AAPL")
            return price is not None and price > 0
        except Exception as e:
            logger.warning(f"YFinance connection test failed: {e}")
            return False

    async def close(self) -> None:
        """Close the gateway (no-op for paper trading)."""
        pass

    def __repr__(self) -> str:
        return (
            f"StockPaperExecutionGateway("
            f"fee_bps={self._fee_bps}, "
            f"slippage_bps={self._slippage_bps}, "
            f"enforce_market_hours={self._enforce_market_hours})"
        )
