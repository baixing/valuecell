"""Stock market data source using YFinance.

Provides market data for US stocks via Yahoo Finance API.
Suitable for paper trading and backtesting stock strategies.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

from loguru import logger

from valuecell.agents.common.trading.models import (
    Candle,
    InstrumentRef,
    MarketSnapShotType,
)

from .interfaces import BaseMarketDataSource


class StockMarketDataSource(BaseMarketDataSource):
    """Market data source for US stocks using YFinance.

    Fetches real-time and historical price data from Yahoo Finance.
    Suitable for paper trading simulations with 15-minute delayed data.
    """

    def __init__(self) -> None:
        """Initialize the stock market data source."""
        self._yf_adapter: Optional["YFinanceAdapter"] = None

    def _get_adapter(self) -> "YFinanceAdapter":
        """Lazy-load YFinanceAdapter to avoid circular imports."""
        if self._yf_adapter is None:
            from valuecell.adapters.assets.yfinance_adapter import YFinanceAdapter

            self._yf_adapter = YFinanceAdapter()
        return self._yf_adapter

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format for YFinance.

        Converts internal format (e.g., 'AAPL-USD', 'AAPL') to YFinance format.

        Args:
            symbol: Symbol in internal format

        Returns:
            Normalized symbol for YFinance
        """
        # Remove any suffix like -USD, -USDT for stocks
        if "-" in symbol:
            symbol = symbol.split("-")[0]
        return symbol.upper()

    async def get_recent_candles(
        self, symbols: List[str], interval: str, lookback: int
    ) -> List[Candle]:
        """Fetch recent candles for the given symbols.

        Args:
            symbols: List of stock symbols (e.g., ['AAPL', 'TSLA'])
            interval: Candle interval (e.g., '1m', '5m', '1d')
            lookback: Number of candles to retrieve

        Returns:
            List of Candle objects
        """

        async def _fetch_symbol(symbol: str) -> List[Candle]:
            try:
                import yfinance as yf

                normalized = self._normalize_symbol(symbol)
                ticker = yf.Ticker(normalized)

                # Map interval to yfinance format
                interval_map = {
                    "1s": "1m",  # yfinance doesn't support 1s, use 1m
                    "1m": "1m",
                    "2m": "2m",
                    "5m": "5m",
                    "15m": "15m",
                    "30m": "30m",
                    "60m": "60m",
                    "1h": "1h",
                    "1d": "1d",
                    "1w": "1wk",
                    "1M": "1mo",
                }
                yf_interval = interval_map.get(interval, "1d")

                # Determine period based on interval and lookback
                if yf_interval in ("1m", "2m", "5m", "15m", "30m"):
                    # For intraday, max 7 days of data
                    period = "7d"
                elif yf_interval in ("60m", "1h"):
                    period = "60d"
                else:
                    period = "1y"

                # Run synchronous yfinance call in executor
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda: ticker.history(period=period, interval=yf_interval),
                )

                if data is None or data.empty:
                    logger.warning(f"No candle data for {normalized}")
                    return []

                # Take only the last `lookback` candles
                data = data.tail(lookback)

                candles: List[Candle] = []
                for idx, row in data.iterrows():
                    ts = int(idx.timestamp() * 1000)  # Convert to milliseconds
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
                return candles

            except Exception as e:
                logger.warning(f"Failed to fetch candles for {symbol}: {e}")
                return []

        # Fetch all symbols concurrently
        tasks = [_fetch_symbol(s) for s in symbols]
        results = await asyncio.gather(*tasks)

        # Flatten results
        all_candles: List[Candle] = []
        for candle_list in results:
            all_candles.extend(candle_list)

        logger.debug(
            f"Fetched {len(all_candles)} candles for {len(symbols)} symbols, interval={interval}"
        )
        return all_candles

    async def get_market_snapshot(self, symbols: List[str]) -> MarketSnapShotType:
        """Fetch latest prices for the given symbols.

        Args:
            symbols: List of stock symbols

        Returns:
            Dictionary mapping symbol to price data
        """
        snapshot: MarketSnapShotType = {}

        async def _fetch_price(symbol: str) -> tuple[str, dict]:
            try:
                import yfinance as yf

                normalized = self._normalize_symbol(symbol)
                ticker = yf.Ticker(normalized)

                # Run synchronous yfinance call in executor
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(
                    None,
                    lambda: ticker.history(period="1d", interval="1m"),
                )

                if data is None or data.empty:
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
                            return symbol, {
                                "price": {
                                    "symbol": normalized,
                                    "last": float(price),
                                    "timestamp": int(datetime.now().timestamp() * 1000),
                                }
                            }
                    return symbol, {}

                latest = data.iloc[-1]
                ts = int(latest.name.timestamp() * 1000)

                return symbol, {
                    "price": {
                        "symbol": normalized,
                        "last": float(latest["Close"]),
                        "open": float(latest["Open"]),
                        "high": float(latest["High"]),
                        "low": float(latest["Low"]),
                        "close": float(latest["Close"]),
                        "volume": float(latest["Volume"]),
                        "timestamp": ts,
                    }
                }

            except Exception as e:
                logger.warning(f"Failed to fetch market snapshot for {symbol}: {e}")
                return symbol, {}

        # Fetch all symbols concurrently
        tasks = [_fetch_price(s) for s in symbols]
        results = await asyncio.gather(*tasks)

        for symbol, data in results:
            if data:
                snapshot[symbol] = data

        logger.debug(f"Fetched market snapshot for {len(snapshot)} symbols")
        return snapshot
