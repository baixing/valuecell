from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from valuecell.server.db.repositories.strategy_repository import get_strategy_repository
from valuecell.utils.ts import get_current_timestamp_ms
from valuecell.utils.uuid import generate_uuid

from ..data.backtest import BacktestDataSource
from ..data.stock_backtest import StockBacktestDataSource
from ..decision import BaseComposer, LlmComposer
from ..execution import BaseExecutionGateway
from ..execution.factory import create_execution_gateway
from ..features import DefaultFeaturesPipeline
from ..features.interfaces import BaseFeaturesPipeline
from ..history import (
    InMemoryHistoryRecorder,
    RollingDigestBuilder,
)
from ..models import AssetClass, Constraints, DecisionCycleResult, TradingMode, UserRequest
from ..portfolio.in_memory import InMemoryPortfolioService
from ..utils import fetch_free_cash_from_gateway, fetch_positions_from_gateway
from .coordinator import DefaultDecisionCoordinator


async def _create_execution_gateway(request: UserRequest) -> BaseExecutionGateway:
    """Create execution gateway asynchronously, handling LIVE mode balance fetching."""
    execution_gateway = await create_execution_gateway(request.exchange_config)

    # In LIVE mode, fetch exchange balance and set initial capital from free cash
    try:
        if request.exchange_config.trading_mode == TradingMode.LIVE:
            free_cash, total_cash = await fetch_free_cash_from_gateway(
                execution_gateway, request.trading_config.symbols
            )
            request.trading_config.initial_free_cash = float(free_cash)
            request.trading_config.initial_capital = float(total_cash)
            request.trading_config.initial_positions = (
                await fetch_positions_from_gateway(execution_gateway)
            )
    except Exception:
        # Log the error but continue - user might have set initial portfolio manually
        logger.exception(
            "Failed to fetch exchange portfolio for LIVE mode. Will use configured initial portfolio instead."
        )

    # Validate initial capital for LIVE mode
    if request.exchange_config.trading_mode == TradingMode.LIVE:
        initial_total_cash = request.trading_config.initial_capital or 0.0
        if initial_total_cash <= 0:
            logger.error(
                f"LIVE trading mode has initial_total_cash={initial_total_cash}. "
                "This usually means balance fetch failed or account has no funds. "
                "Strategy will not be able to trade without capital."
            )

    return execution_gateway


@dataclass
class StrategyRuntime:
    request: UserRequest
    strategy_id: str
    coordinator: DefaultDecisionCoordinator
    backtest_data_source: Optional[BacktestDataSource | StockBacktestDataSource] = field(
        default=None
    )

    def get_current_timestamp_ms(self) -> int:
        """Get current timestamp in milliseconds.

        For backtest mode, returns the simulated time from BacktestDataSource.
        For live/virtual mode, returns the actual current time.
        """
        if (
            self.backtest_data_source is not None
            and self.request.exchange_config.trading_mode == TradingMode.BACKTEST
        ):
            return self.backtest_data_source.get_current_ts()
        return get_current_timestamp_ms()

    async def run_cycle(self) -> DecisionCycleResult:
        """Execute one decision cycle.

        Uses simulated time for backtest mode, real time otherwise.
        """
        timestamp_ms = self.get_current_timestamp_ms()
        return await self.coordinator.run_once(timestamp_ms=timestamp_ms)


async def create_strategy_runtime(
    request: UserRequest,
    composer: Optional[BaseComposer] = None,
    features_pipeline: Optional[BaseFeaturesPipeline] = None,
    strategy_id_override: Optional[str] = None,
) -> StrategyRuntime:
    """Create a strategy runtime with async initialization (supports both paper and live trading).

    This function properly initializes CCXT exchange connections for live trading
    and can also be used for paper trading.

    In LIVE mode, it fetches the exchange balance and sets the
    initial capital to the available (free) cash for the strategy's
    quote currencies. Opening positions will therefore draw down cash
    and cannot borrow (no financing).

    Args:
        request: User request with strategy configuration
        composer: Optional custom decision composer. If None, uses LlmComposer.
        features_pipeline: Optional custom features pipeline. If None, uses
            `DefaultFeaturesPipeline`.

    Returns:
        StrategyRuntime instance with initialized execution gateway

    Example:
        >>> request = UserRequest(
        ...     exchange_config=ExchangeConfig(
        ...         exchange_id='binance',
        ...         trading_mode=TradingMode.LIVE,
        ...         api_key='YOUR_KEY',
        ...         secret_key='YOUR_SECRET',
        ...         market_type=MarketType.SWAP,
        ...         margin_mode=MarginMode.ISOLATED,
        ...         testnet=True,
        ...     ),
        ...     trading_config=TradingConfig(
        ...         symbols=['BTC-USDT', 'ETH-USDT'],
        ...         initial_capital=10000.0,
        ...         initial_free_cash=10000.0,
        ...         max_leverage=10.0,
        ...         max_positions=5,
        ...     )
        ... )
        >>> runtime = await create_strategy_runtime(request)
    """
    # Create execution gateway asynchronously
    execution_gateway = await _create_execution_gateway(request)

    # Create strategy runtime components
    strategy_id = strategy_id_override or generate_uuid("strategy")

    # For backtest mode, create and preload the backtest data source
    backtest_data_source: Optional[BacktestDataSource | StockBacktestDataSource] = None
    if request.exchange_config.trading_mode == TradingMode.BACKTEST:
        start_ts = request.trading_config.backtest_start_ts
        end_ts = request.trading_config.backtest_end_ts
        if not start_ts or not end_ts:
            raise ValueError(
                "Backtest mode requires backtest_start_ts and backtest_end_ts"
            )
        if start_ts >= end_ts:
            raise ValueError("backtest_start_ts must be less than backtest_end_ts")

        is_stock = request.exchange_config.asset_class == AssetClass.STOCK

        logger.info(
            "Preloading backtest data for strategy_id={}, range={} to {}",
            strategy_id,
            start_ts,
            end_ts,
        )

        if is_stock:
            # US stock backtest uses YFinance data source with daily candles
            backtest_data_source = StockBacktestDataSource(
                symbols=request.trading_config.symbols,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            await backtest_data_source.preload_data(intervals=["1d"])
        else:
            # Crypto backtest uses CCXT data source with 1-minute candles
            exchange_id = request.exchange_config.exchange_id or "okx"
            backtest_data_source = BacktestDataSource(
                exchange_id=exchange_id,
                symbols=request.trading_config.symbols,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            await backtest_data_source.preload_data(intervals=["1m"])

    # If this is a resume of an existing strategy,
    # attempt to initialize from the persisted portfolio snapshot
    # so the in-memory portfolio starts with the previously recorded equity.
    free_cash_override = None
    total_cash_override = None
    if strategy_id_override:
        try:
            repo = get_strategy_repository()
            snap = repo.get_latest_portfolio_snapshot(strategy_id_override)
            if snap is not None:
                free_cash_override = float(snap.cash or 0.0)
                total_cash_override = float(
                    snap.total_value - snap.total_unrealized_pnl
                    if (
                        snap.total_value is not None
                        and snap.total_unrealized_pnl is not None
                    )
                    else 0.0
                )
                logger.info(
                    "Initialized runtime initial capital from persisted snapshot for strategy_id=%s",
                    strategy_id_override,
                )
        except Exception:
            logger.exception(
                "Failed to initialize initial capital from persisted snapshot for strategy_id=%s",
                strategy_id_override,
            )

    free_cash = free_cash_override or request.trading_config.initial_free_cash or 0.0
    total_cash = total_cash_override or request.trading_config.initial_capital or 0.0
    constraints = Constraints(
        max_positions=request.trading_config.max_positions,
        max_leverage=request.trading_config.max_leverage,
    )
    portfolio_service = InMemoryPortfolioService(
        free_cash=free_cash,
        total_cash=total_cash,
        initial_positions=request.trading_config.initial_positions,
        trading_mode=request.exchange_config.trading_mode,
        market_type=request.exchange_config.market_type,
        constraints=constraints,
        strategy_id=strategy_id,
    )

    # Use custom composer if provided, otherwise default to LlmComposer
    if composer is None:
        composer = LlmComposer(request=request)

    if features_pipeline is None:
        features_pipeline = DefaultFeaturesPipeline.from_request(
            request, backtest_data_source=backtest_data_source
        )

    history_recorder = InMemoryHistoryRecorder()
    digest_builder = RollingDigestBuilder()

    coordinator = DefaultDecisionCoordinator(
        request=request,
        strategy_id=strategy_id,
        portfolio_service=portfolio_service,
        features_pipeline=features_pipeline,
        composer=composer,
        execution_gateway=execution_gateway,
        history_recorder=history_recorder,
        digest_builder=digest_builder,
    )

    # If resuming an existing strategy, initialize coordinator cycle index
    # from the latest persisted compose cycle so the in-memory coordinator
    # continues numbering without overlap.
    if strategy_id_override:
        try:
            repo = get_strategy_repository()
            cycles = repo.get_cycles(strategy_id, limit=1)
            if cycles:
                latest = cycles[0]
                if latest.cycle_index is not None:
                    coordinator.cycle_index = int(latest.cycle_index)
        except Exception:
            logger.exception(
                "Failed to initialize coordinator cycle_index from DB for strategy_id=%s",
                strategy_id,
            )

    return StrategyRuntime(
        request=request,
        strategy_id=strategy_id,
        coordinator=coordinator,
        backtest_data_source=backtest_data_source,
    )
