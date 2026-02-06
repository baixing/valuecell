"""Execution adapters for trading instructions."""

from .ccxt_trading import CCXTExecutionGateway, create_ccxt_gateway
from .factory import create_execution_gateway, create_execution_gateway_sync
from .interfaces import BaseExecutionGateway
from .paper_trading import PaperExecutionGateway
from .stock_paper_trading import StockPaperExecutionGateway, is_us_market_open

__all__ = [
    "BaseExecutionGateway",
    "PaperExecutionGateway",
    "StockPaperExecutionGateway",
    "CCXTExecutionGateway",
    "create_ccxt_gateway",
    "create_execution_gateway",
    "create_execution_gateway_sync",
    "is_us_market_open",
]
