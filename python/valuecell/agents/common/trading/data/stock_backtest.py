"""Stock backtest data source using YFinance for historical data replay.

Provides historical daily candle data for US stocks via Yahoo Finance API.
This is the stock equivalent of BacktestDataSource (which uses CCXT for crypto).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from loguru import logger

from valuecell.agents.common.trading.models import (
    Candle,
    InstrumentRef,
    MarketSnapShotType,
)

from .interfaces import BaseMarketDataSource


class StockBacktestDataSource(BaseMarketDataSource):
    """Data source that replays historical US stock data for backtesting.

    Uses YFinance to preload daily OHLCV data for the specified time range,
    then replays it by maintaining a simulated current time pointer.

    Key features:
    - Preloads all historical daily data upfront from YFinance
    - Maintains a current_ts pointer for simulated time
    - Returns only data that would have been available at current_ts
    - Provides progress tracking for UI feedback

    Unlike BacktestDataSource (which uses CCXT for crypto), this class
    fetches data from Yahoo Finance which supports US stock symbols.
    """

    def __init__(
        self,
        symbols: List[str],
        start_ts: int,
        end_ts: int,
    ) -> None:
        """Initialize the stock backtest data source.

        Args:
            symbols: List of stock symbols to backtest (e.g., ['QQQ', 'SPY'])
            start_ts: Backtest start timestamp in milliseconds
            end_ts: Backtest end timestamp in milliseconds
        """
        self._symbols = symbols
        self._start_ts = start_ts
        self._end_ts = end_ts
        self._current_ts = start_ts

        # Cache for preloaded historical data: {symbol: {interval: [Candle, ...]}}
        self._candle_cache: Dict[str, Dict[str, List[Candle]]] = defaultdict(
            lambda: defaultdict(list)
        )

        self._is_preloaded = False

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format for YFinance.

        Converts internal format (e.g., 'AAPL-USD', 'AAPL') to YFinance format.

        Args:
            symbol: Symbol in internal format

        Returns:
            Normalized symbol for YFinance
        """
        if "-" in symbol:
            symbol = symbol.split("-")[0]
        return symbol.upper()

    async def preload_data(self, intervals: Optional[List[str]] = None) -> None:
        """Preload historical data for all symbols and intervals.

        This should be called once before starting the backtest loop.
        Downloads all historical candles from start_ts to end_ts via YFinance.

        Args:
            intervals: List of candle intervals to preload (default: ['1d'])
        """
        if self._is_preloaded:
            logger.info("Stock backtest data already preloaded, skipping")
            return

        intervals = intervals or ["1d"]
        logger.info(
            "Preloading stock backtest data for {} symbols, intervals={}, range={} to {}",
            len(self._symbols),
            intervals,
            self._start_ts,
            self._end_ts,
        )

        for interval in intervals:
            await self._preload_interval(interval)

        self._is_preloaded = True
        total_candles = sum(
            len(candles)
            for symbol_data in self._candle_cache.values()
            for candles in symbol_data.values()
        )
        logger.info(
            "Stock backtest data preload complete: {} total candles loaded",
            total_candles,
        )

    async def _preload_interval(self, interval: str) -> None:
        """Preload candles for a specific interval using YFinance."""

        # Map internal interval to yfinance format
        interval_map = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "1d": "1d",
            "1w": "1wk",
            "1M": "1mo",
        }
        yf_interval = interval_map.get(interval, "1d")

        # Convert millisecond timestamps to datetime for YFinance
        start_dt = datetime.fromtimestamp(self._start_ts / 1000, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(self._end_ts / 1000, tz=timezone.utc)

        # Format as date strings for YFinance
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        async def _fetch_symbol(symbol: str) -> List[Candle]:
            try:
                import yfinance as yf

                normalized = self._normalize_symbol(symbol)
                ticker = yf.Ticker(normalized)

                # Run synchronous yfinance call in executor
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda: ticker.history(
                        start=start_str,
                        end=end_str,
                        interval=yf_interval,
                    ),
                )

                if data is None or data.empty:
                    logger.warning(
                        "No historical data for {} ({}) from YFinance",
                        symbol,
                        normalized,
                    )
                    return []

                candles: List[Candle] = []
                for idx, row in data.iterrows():
                    ts = int(idx.timestamp() * 1000)
                    # Only include candles within the backtest range
                    if ts > self._end_ts:
                        break
                    candles.append(
                        Candle(
                            ts=ts,
                            instrument=InstrumentRef(
                                symbol=symbol,
                                exchange_id="yfinance",
                            ),
                            open=float(row["Open"]),
                            high=float(row["High"]),
                            low=float(row["Low"]),
                            close=float(row["Close"]),
                            volume=float(row["Volume"]),
                            interval=interval,
                        )
                    )

                logger.debug(
                    "Loaded {} candles for {} interval {} from YFinance",
                    len(candles),
                    symbol,
                    interval,
                )
                return candles

            except Exception as exc:
                logger.warning(
                    "Failed to fetch historical candles for {} ({}): {}",
                    symbol,
                    interval,
                    exc,
                )
                return []

        # Fetch all symbols concurrently
        tasks = [_fetch_symbol(symbol) for symbol in self._symbols]
        results = await asyncio.gather(*tasks)

        for symbol, candles in zip(self._symbols, results):
            self._candle_cache[symbol][interval] = sorted(candles, key=lambda c: c.ts)

    async def get_recent_candles(
        self, symbols: List[str], interval: str, lookback: int
    ) -> List[Candle]:
        """Return historical candles up to the current simulated time.

        Only returns candles with timestamps <= current_ts to simulate
        what data would have been available at that point in time.

        Args:
            symbols: List of symbols to get candles for
            interval: Candle interval (e.g., '1d')
            lookback: Number of candles to return per symbol

        Returns:
            List of Candle objects available at current_ts
        """
        result: List[Candle] = []

        for symbol in symbols:
            candles = self._candle_cache.get(symbol, {}).get(interval, [])
            # Filter candles that would have been available at current_ts
            available = [c for c in candles if c.ts <= self._current_ts]
            # Return the most recent `lookback` candles
            result.extend(available[-lookback:] if available else [])

        return result

    async def get_market_snapshot(self, symbols: List[str]) -> MarketSnapShotType:
        """Return market snapshot based on the most recent candle at current_ts.

        Simulates a market snapshot using the close price from the most
        recent candle available at the current simulated time.

        Args:
            symbols: List of symbols to get snapshot for

        Returns:
            Dict mapping symbol to price data
        """
        snapshot: Dict[str, Dict] = {}

        for symbol in symbols:
            # Find the most recent candle for this symbol at current_ts
            # Try 1d interval as it's the primary interval for stock backtests
            candles = self._candle_cache.get(symbol, {}).get("1d", [])
            available = [c for c in candles if c.ts <= self._current_ts]

            if available:
                latest = available[-1]
                snapshot[symbol] = {
                    "price": {
                        "symbol": symbol,
                        "timestamp": latest.ts,
                        "last": latest.close,
                        "close": latest.close,
                        "open": latest.open,
                        "high": latest.high,
                        "low": latest.low,
                        "volume": latest.volume,
                    }
                }

        return snapshot

    # ------------------------------------------------------------------
    # Time management methods (identical to BacktestDataSource)
    # ------------------------------------------------------------------

    def advance_time(self, interval_ms: int) -> None:
        """Advance the simulated current time.

        Args:
            interval_ms: Time to advance in milliseconds
        """
        self._current_ts += interval_ms

    def is_finished(self) -> bool:
        """Check if the backtest has reached the end time.

        Returns:
            True if current_ts >= end_ts
        """
        return self._current_ts >= self._end_ts

    def get_progress_pct(self) -> float:
        """Get the current backtest progress as a percentage.

        Returns:
            Progress percentage (0-100)
        """
        if self._end_ts <= self._start_ts:
            return 100.0
        elapsed = self._current_ts - self._start_ts
        total = self._end_ts - self._start_ts
        return min(100.0, (elapsed / total) * 100.0)

    def get_current_ts(self) -> int:
        """Get the current simulated timestamp.

        Returns:
            Current timestamp in milliseconds
        """
        return self._current_ts

    def reset(self) -> None:
        """Reset the backtest to the start time."""
        self._current_ts = self._start_ts
