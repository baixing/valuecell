"""Backtest data source for historical data replay.

This module provides a data source that replays historical candle data
for backtesting strategies without real-time market connections.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Dict, List, Optional

from loguru import logger

from valuecell.agents.common.trading.models import (
    Candle,
    InstrumentRef,
    MarketSnapShotType,
)
from valuecell.agents.common.trading.utils import get_exchange_cls, normalize_symbol

from .interfaces import BaseMarketDataSource


class BacktestDataSource(BaseMarketDataSource):
    """Data source that replays historical candle data for backtesting.

    This class preloads historical data from an exchange for a specified
    time range, then replays it by maintaining a simulated current time
    pointer that advances through the data.

    Key features:
    - Preloads all historical data upfront to avoid API calls during backtest
    - Maintains a current_ts pointer for simulated time
    - Returns only data that would have been available at current_ts
    - Provides progress tracking for UI feedback
    """

    def __init__(
        self,
        exchange_id: str,
        symbols: List[str],
        start_ts: int,
        end_ts: int,
    ) -> None:
        """Initialize the backtest data source.

        Args:
            exchange_id: Exchange to fetch historical data from (e.g., 'okx', 'binance')
            symbols: List of symbols to backtest (e.g., ['BTC-USDT', 'ETH-USDT'])
            start_ts: Backtest start timestamp in milliseconds
            end_ts: Backtest end timestamp in milliseconds
        """
        self._exchange_id = exchange_id or "okx"
        self._symbols = symbols
        self._start_ts = start_ts
        self._end_ts = end_ts
        self._current_ts = start_ts

        # Cache for preloaded historical data: {symbol: {interval: [Candle, ...]}}
        self._candle_cache: Dict[str, Dict[str, List[Candle]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # Cache for market snapshots derived from candle data
        self._snapshot_cache: Dict[str, Dict[str, Candle]] = defaultdict(dict)

        self._is_preloaded = False

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format for CCXT."""
        base_symbol = symbol.replace("-", "/")
        if ":" not in base_symbol:
            parts = base_symbol.split("/")
            if len(parts) == 2:
                base_symbol = f"{parts[0]}/{parts[1]}:{parts[1]}"
        return base_symbol

    async def preload_data(self, intervals: Optional[List[str]] = None) -> None:
        """Preload historical data for all symbols and intervals.

        This should be called once before starting the backtest loop.
        Downloads all historical candles from start_ts to end_ts.

        Args:
            intervals: List of candle intervals to preload (default: ['1m'])
        """
        if self._is_preloaded:
            logger.info("Backtest data already preloaded, skipping")
            return

        intervals = intervals or ["1m"]
        logger.info(
            "Preloading backtest data for {} symbols, intervals={}, range={} to {}",
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
            "Backtest data preload complete: {} total candles loaded", total_candles
        )

    async def _preload_interval(self, interval: str) -> None:
        """Preload candles for a specific interval."""

        async def _fetch_symbol(symbol: str) -> List[Candle]:
            exchange_cls = get_exchange_cls(self._exchange_id)
            exchange = exchange_cls({"newUpdates": False})
            candles: List[Candle] = []
            normalized_symbol = self._normalize_symbol(symbol)

            try:
                # Fetch historical OHLCV data
                # CCXT fetch_ohlcv with since parameter returns candles from that timestamp
                raw = await exchange.fetch_ohlcv(
                    normalized_symbol,
                    timeframe=interval,
                    since=self._start_ts,
                    limit=1000,  # Max limit per request
                )

                # If we need more data, paginate
                while raw:
                    for row in raw:
                        ts, open_v, high_v, low_v, close_v, vol = row
                        if ts > self._end_ts:
                            break
                        candles.append(
                            Candle(
                                ts=int(ts),
                                instrument=InstrumentRef(
                                    symbol=symbol,
                                    exchange_id=self._exchange_id,
                                ),
                                open=float(open_v),
                                high=float(high_v),
                                low=float(low_v),
                                close=float(close_v),
                                volume=float(vol),
                                interval=interval,
                            )
                        )

                    # Check if we need more data
                    if not raw or raw[-1][0] >= self._end_ts:
                        break

                    # Fetch next batch starting from last candle timestamp
                    last_ts = raw[-1][0]
                    await asyncio.sleep(0.1)  # Rate limiting
                    raw = await exchange.fetch_ohlcv(
                        normalized_symbol,
                        timeframe=interval,
                        since=last_ts + 1,
                        limit=1000,
                    )

                logger.debug(
                    "Loaded {} candles for {} interval {} from {}",
                    len(candles),
                    symbol,
                    interval,
                    self._exchange_id,
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
            finally:
                try:
                    await exchange.close()
                except Exception:
                    pass

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
            interval: Candle interval (e.g., '1m', '5m')
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
            # Try 1m interval first as it's most granular
            candles = self._candle_cache.get(symbol, {}).get("1m", [])
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
                    }
                }

        return snapshot

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
