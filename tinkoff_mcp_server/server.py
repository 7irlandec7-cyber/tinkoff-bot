"""
Tinkoff MCP Server - Main Server Module
"""
import logging
import sys
from typing import Optional
from fastapi import FastAPI
from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('tinkoff_mcp.log')
    ]
)

logger = logging.getLogger(__name__)

# Import configuration and tools
from .config import get_settings, validate_config
from . import tools

# Create FastMCP server
mcp = FastMCP(name="Tinkoff Invest MCP Server")

# Create FastAPI app for health checks
app = FastAPI(title="Tinkoff MCP Server")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "tinkoff-mcp-server"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Tinkoff Invest MCP Server",
        "version": "1.0.0",
        "status": "running"
    }


# =============================================================================
# MCP Tools Registration
# =============================================================================

@mcp.tool()
async def get_portfolio() -> dict:
    """Get current portfolio with all holdings."""
    return await tools.get_portfolio()


@mcp.tool()
async def get_positions() -> dict:
    """Get detailed open positions."""
    return await tools.get_positions()


@mcp.tool()
async def get_currencies() -> dict:
    """Get currency balances."""
    return await tools.get_currencies()


@mcp.tool()
async def get_portfolio_summary() -> dict:
    """Get portfolio summary with key metrics."""
    return await tools.get_portfolio_summary()


@mcp.tool()
async def get_orders() -> dict:
    """Get open orders."""
    return await tools.get_orders()


@mcp.tool()
async def get_order_state(order_id: str) -> dict:
    """Get specific order state."""
    return await tools.get_order_state(order_id)


@mcp.tool()
async def place_market_order(
    figi: str,
    quantity: int,
    direction: str
) -> dict:
    """Place market order (BUY or SELL).
    
    Args:
        figi: Instrument FIGI
        quantity: Number of lots
        direction: 'BUY' or 'SELL'
    """
    return await tools.place_market_order(figi, quantity, direction)


@mcp.tool()
async def place_limit_order(
    figi: str,
    quantity: int,
    direction: str,
    price: float
) -> dict:
    """Place limit order.
    
    Args:
        figi: Instrument FIGI
        quantity: Number of lots
        direction: 'BUY' or 'SELL'
        price: Limit price
    """
    return await tools.place_limit_order(figi, quantity, direction, price)


@mcp.tool()
async def cancel_order(order_id: str) -> dict:
    """Cancel an order."""
    return await tools.cancel_order(order_id)


@mcp.tool()
async def get_operations(days: int = 30) -> dict:
    """Get operations history.
    
    Args:
        days: Number of days to look back (default: 30)
    """
    return await tools.get_operations(days)


@mcp.tool()
async def get_candles(
    figi: str,
    days: int = 7,
    interval: str = "hour"
) -> dict:
    """Get historical candles.
    
    Args:
        figi: Instrument FIGI
        days: Number of days to look back (default: 7)
        interval: Candle interval - 1min, 5min, 15min, hour, day, week (default: hour)
    """
    return await tools.get_candles(figi, days, interval)


@mcp.tool()
async def get_last_price(figi: str) -> dict:
    """Get last price for instrument."""
    return await tools.get_last_price(figi)


@mcp.tool()
async def get_orderbook(figi: str, depth: int = 10) -> dict:
    """Get orderbook (bid/ask quotes).
    
    Args:
        figi: Instrument FIGI
        depth: Number of price levels (default: 10)
    """
    return await tools.get_orderbook(figi, depth)


@mcp.tool()
async def get_trading_status(figi: str) -> dict:
    """Get trading status for instrument."""
    return await tools.get_trading_status(figi)


@mcp.tool()
async def get_accounts() -> dict:
    """Get list of broker accounts."""
    return await tools.get_accounts()


@mcp.tool()
async def get_instrument_info(figi: str) -> dict:
    """Get detailed instrument information."""
    return await tools.get_instrument_info(figi)


@mcp.tool()
async def search_instrument(
    ticker: str,
    instrument_type: Optional[str] = None
) -> dict:
    """Search instrument by ticker.
    
    Args:
        ticker: Instrument ticker (e.g., 'SBER', 'AAPL')
        instrument_type: Optional filter - Stock, Bond, Etf
    """
    return await tools.search_instrument(ticker, instrument_type)


# =============================================================================
# Server Lifecycle
# =============================================================================

def run_server():
    """Run the MCP server."""
    settings = get_settings()
    
    # Validate configuration
    errors = validate_config()
    if errors:
        logger.error("Configuration errors:")
        for error in errors:
            logger.error(f"  - {error}")
        logger.error("Please fix configuration and try again.")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("Tinkoff Invest MCP Server")
    logger.info("=" * 60)
    logger.info(f"Server: {settings.mcp_server_host}:{settings.mcp_server_port}")
    logger.info(f"API URL: {settings.tinkoff_api_url}")
    logger.info(f"Dry Run: {settings.dry_run}")
    logger.info("=" * 60)
    
    # Run MCP server
    mcp.run(transport="streamable-http", port=settings.mcp_server_port)


if __name__ == "__main__":
    run_server()
