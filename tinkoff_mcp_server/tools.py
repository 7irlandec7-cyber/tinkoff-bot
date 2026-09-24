"""
Tinkoff MCP Server - MCP Tools Module
"""
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
from .tinkoff_client import TinkoffClient, TinkoffAPIError
from .config import get_settings

logger = logging.getLogger(__name__)

# Global client instance
_client: Optional[TinkoffClient] = None


def get_client() -> TinkoffClient:
    """Get or create Tinkoff client instance."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = TinkoffClient(
            token=settings.tinkoff_token,
            account_id=settings.tinkoff_account_id
        )
    return _client


def set_client(client: TinkoffClient) -> None:
    """Set Tinkoff client instance (for testing)."""
    global _client
    _client = client


# =============================================================================
# Portfolio Tools
# =============================================================================

async def get_portfolio() -> Dict[str, Any]:
    """
    Get current portfolio with all holdings.
    
    Returns:
        Portfolio data including positions, total value, and P&L
    """
    try:
        client = get_client()
        portfolio = client.get_portfolio()
        
        # Calculate totals
        total_value = 0.0
        total_profit = 0.0
        
        positions = []
        for pos in portfolio.get("positions", []):
            current_value = float(pos.get("currentValue", {}).get("units", 0))
            average_price = float(pos.get("averagePositionPrice", {}).get("units", 0))
            quantity = int(pos.get("quantity", {}).get("units", 0))
            profit = current_value - (average_price * quantity)
            profit_percent = (profit / (average_price * quantity) * 100) if average_price > 0 else 0
            
            total_value += current_value
            total_profit += profit
            
            positions.append({
                "figi": pos.get("figi"),
                "ticker": pos.get("ticker"),
                "name": pos.get("name"),
                "instrument_type": pos.get("instrumentType"),
                "quantity": quantity,
                "average_price": average_price,
                "current_value": current_value,
                "profit": profit,
                "profit_percent": round(profit_percent, 2)
            })
        
        return {
            "success": True,
            "account_id": portfolio.get("accountId"),
            "total_value": total_value,
            "total_profit": round(total_profit, 2),
            "profit_percent": round((total_profit / (total_value - total_profit) * 100) if total_value > total_profit else 0, 2),
            "positions": positions,
            "positions_count": len(positions)
        }
    except TinkoffAPIError as e:
        logger.error(f"Portfolio error: {e}")
        return {"success": False, "error": e.message}
    except Exception as e:
        logger.error(f"Portfolio error: {e}")
        return {"success": False, "error": str(e)}


async def get_positions() -> Dict[str, Any]:
    """
    Get open positions (detailed view).
    
    Returns:
        Detailed positions data including blocked and available quantities
    """
    try:
        client = get_client()
        positions = client.get_positions()
        
        result = {
            "success": True,
            "securities": [],
            "money": []
        }
        
        for sec in positions.get("securities", []):
            result["securities"].append({
                "figi": sec.get("figi"),
                "ticker": sec.get("ticker"),
                "name": sec.get("name"),
                "instrument_type": sec.get("instrumentType"),
                "blocked": int(sec.get("blocked", 0)),
                "balance": int(sec.get("balance", 0))
            })
        
        for cur in positions.get("money", []):
            result["money"].append({
                "currency": cur.get("currency"),
                "balance": float(cur.get("balance", 0)),
                "blocked": float(cur.get("blocked", 0))
            })
        
        return result
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_currencies() -> Dict[str, Any]:
    """
    Get currency positions and account balances.
    
    Returns:
        Currency balances in all currencies
    """
    try:
        client = get_client()
        currencies = client.get_portfolio_currencies()
        
        result = {
            "success": True,
            "currencies": []
        }
        
        for cur in currencies.get("currencies", []):
            result["currencies"].append({
                "currency": cur.get("currency"),
                "balance": float(cur.get("balance", 0)),
                "blocked": float(cur.get("blocked", 0)),
                "available": float(cur.get("balance", 0)) - float(cur.get("blocked", 0))
            })
        
        return result
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_portfolio_summary() -> Dict[str, Any]:
    """
    Get portfolio summary with key metrics.
    
    Returns:
        Summary including total value, P&L, and allocation
    """
    try:
        client = get_client()
        
        portfolio = client.get_portfolio()
        currencies = client.get_portfolio_currencies()
        
        # Calculate values
        positions_data = portfolio.get("positions", [])
        currencies_data = currencies.get("currencies", [])
        
        total_stocks = 0.0
        total_bonds = 0.0
        total_etf = 0.0
        total_other = 0.0
        total_cash = 0.0
        
        # Calculate by instrument type
        for pos in positions_data:
            value = float(pos.get("currentValue", {}).get("units", 0))
            inst_type = pos.get("instrumentType", "")
            
            if inst_type == "Stock":
                total_stocks += value
            elif inst_type == "Bond":
                total_bonds += value
            elif inst_type == "Etf":
                total_etf += value
            else:
                total_other += value
        
        # Add cash in RUB
        for cur in currencies_data:
            if cur.get("currency") == "RUB":
                total_cash += float(cur.get("balance", 0))
        
        total_value = total_stocks + total_bonds + total_etf + total_other + total_cash
        
        return {
            "success": True,
            "total_value": round(total_value, 2),
            "allocation": {
                "stocks": {"value": round(total_stocks, 2), "percent": round(total_stocks / total_value * 100 if total_value > 0 else 0, 2)},
                "bonds": {"value": round(total_bonds, 2), "percent": round(total_bonds / total_value * 100 if total_value > 0 else 0, 2)},
                "etf": {"value": round(total_etf, 2), "percent": round(total_etf / total_value * 100 if total_value > 0 else 0, 2)},
                "other": {"value": round(total_other, 2), "percent": round(total_other / total_value * 100 if total_value > 0 else 0, 2)},
                "cash": {"value": round(total_cash, 2), "percent": round(total_cash / total_value * 100 if total_value > 0 else 0, 2)}
            },
            "positions_count": len(positions_data)
        }
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Orders Tools
# =============================================================================

async def get_orders() -> Dict[str, Any]:
    """
    Get open (active) orders.
    
    Returns:
        List of active orders
    """
    try:
        client = get_client()
        orders = client.get_orders()
        
        result = {
            "success": True,
            "orders": []
        }
        
        for order in orders:
            result["orders"].append({
                "order_id": order.get("orderId"),
                "figi": order.get("figi"),
                "ticker": order.get("ticker"),
                "direction": order.get("direction"),
                "type": order.get("orderType"),
                "status": order.get("status"),
                "requested_lots": int(order.get("requestedLots", 0)),
                "executed_lots": int(order.get("executedLots", 0)),
                "price": float(order.get("price", {}).get("units", 0)) if order.get("price") else None,
                "created_at": order.get("createdAt")
            })
        
        return result
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_order_state(order_id: str) -> Dict[str, Any]:
    """
    Get specific order state.
    
    Args:
        order_id: Order ID to check
        
    Returns:
        Detailed order state
    """
    try:
        client = get_client()
        order = client.get_order_state(order_id)
        
        return {
            "success": True,
            "order_id": order.get("orderId"),
            "figi": order.get("figi"),
            "ticker": order.get("ticker"),
            "direction": order.get("direction"),
            "type": order.get("orderType"),
            "status": order.get("status"),
            "requested_lots": int(order.get("requestedLots", 0)),
            "executed_lots": int(order.get("executedLots", 0)),
            "price": float(order.get("price", {}).get("units", 0)) if order.get("price") else None,
            "average_price": float(order.get("averagePrice", {}).get("units", 0)) if order.get("averagePrice") else None,
            "created_at": order.get("createdAt"),
            "updated_at": order.get("updatedAt")
        }
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def place_market_order(
    figi: str,
    quantity: int,
    direction: str,
    dry_run: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Place market order (BUY or SELL).
    
    Args:
        figi: Instrument FIGI
        quantity: Number of lots to trade
        direction: "BUY" or "SELL"
        dry_run: Override dry_run setting
        
    Returns:
        Order result
    """
    settings = get_settings()
    
    if dry_run is None:
        dry_run = settings.dry_run
    
    if dry_run:
        logger.info(f"[DRY RUN] Market order: {direction} {quantity} lots of {figi}")
        return {
            "success": True,
            "dry_run": True,
            "order_id": f"DRY_RUN_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "figi": figi,
            "direction": direction,
            "quantity": quantity,
            "message": "Dry run mode - no actual order placed"
        }
    
    try:
        client = get_client()
        result = client.place_market_order(figi, quantity, direction)
        
        return {
            "success": True,
            "order_id": result.get("orderId"),
            "figi": figi,
            "direction": direction,
            "quantity": quantity,
            "message": "Order placed successfully"
        }
    except TinkoffAPIError as e:
        logger.error(f"Market order error: {e}")
        return {"success": False, "error": e.message}
    except Exception as e:
        logger.error(f"Market order error: {e}")
        return {"success": False, "error": str(e)}


async def place_limit_order(
    figi: str,
    quantity: int,
    direction: str,
    price: float,
    dry_run: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Place limit order.
    
    Args:
        figi: Instrument FIGI
        quantity: Number of lots
        direction: "BUY" or "SELL"
        price: Limit price
        dry_run: Override dry_run setting
        
    Returns:
        Order result
    """
    settings = get_settings()
    
    if dry_run is None:
        dry_run = settings.dry_run
    
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "order_id": f"DRY_RUN_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "figi": figi,
            "direction": direction,
            "quantity": quantity,
            "price": price,
            "message": "Dry run mode - no actual order placed"
        }
    
    try:
        client = get_client()
        result = client.place_limit_order(figi, quantity, direction, price)
        
        return {
            "success": True,
            "order_id": result.get("orderId"),
            "figi": figi,
            "direction": direction,
            "quantity": quantity,
            "price": price,
            "message": "Limit order placed successfully"
        }
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def cancel_order(order_id: str) -> Dict[str, Any]:
    """
    Cancel an order.
    
    Args:
        order_id: Order ID to cancel
        
    Returns:
        Cancellation result
    """
    try:
        client = get_client()
        client.cancel_order(order_id)
        
        return {
            "success": True,
            "order_id": order_id,
            "message": "Order cancelled successfully"
        }
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_operations(days: int = 30) -> Dict[str, Any]:
    """
    Get operations history.
    
    Args:
        days: Number of days to look back
        
    Returns:
        Operations history
    """
    try:
        client = get_client()
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days)
        
        operations = client.get_operations(from_date, to_date)
        
        result = {
            "success": True,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "operations": []
        }
        
        for op in operations.get("operations", []):
            result["operations"].append({
                "id": op.get("id"),
                "figi": op.get("figi"),
                "ticker": op.get("ticker"),
                "type": op.get("type"),
                "direction": op.get("direction"),
                "status": op.get("status"),
                "date": op.get("date"),
                "quantity": int(op.get("quantity", 0)),
                "price": float(op.get("price", {}).get("units", 0)) if op.get("price") else None,
                "payment": float(op.get("payment", {}).get("units", 0)) if op.get("payment") else None
            })
        
        return result
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Market Data Tools
# =============================================================================

async def get_candles(
    figi: str,
    days: int = 7,
    interval: str = "1hour"
) -> Dict[str, Any]:
    """
    Get historical candles.
    
    Args:
        figi: Instrument FIGI
        days: Number of days to look back
        interval: Candle interval (1min, 5min, 15min, hour, day, week)
        
    Returns:
        Historical candles data
    """
    try:
        client = get_client()
        
        # Map interval to API format
        interval_map = {
            "1min": "CANDLE_INTERVAL_1_MIN",
            "5min": "CANDLE_INTERVAL_5_MIN",
            "15min": "CANDLE_INTERVAL_15_MIN",
            "hour": "CANDLE_INTERVAL_HOUR",
            "day": "CANDLE_INTERVAL_DAY",
            "week": "CANDLE_INTERVAL_WEEK"
        }
        api_interval = interval_map.get(interval, "CANDLE_INTERVAL_HOUR")
        
        to_time = datetime.now()
        from_time = to_time - timedelta(days=days)
        
        candles = client.get_candles(figi, from_time, to_time, api_interval)
        
        result = {
            "success": True,
            "figi": figi,
            "interval": interval,
            "from": from_time.isoformat(),
            "to": to_time.isoformat(),
            "candles": []
        }
        
        for candle in candles:
            result["candles"].append({
                "time": candle.get("time"),
                "open": float(candle.get("open", {}).get("units", 0)),
                "high": float(candle.get("high", {}).get("units", 0)),
                "low": float(candle.get("low", {}).get("units", 0)),
                "close": float(candle.get("close", {}).get("units", 0)),
                "volume": int(candle.get("volume", 0))
            })
        
        return result
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_last_price(figi: str) -> Dict[str, Any]:
    """
    Get last price for instrument.
    
    Args:
        figi: Instrument FIGI
        
    Returns:
        Last price data
    """
    try:
        client = get_client()
        prices = client.get_last_prices([figi])
        
        if not prices:
            return {"success": False, "error": "No price data available"}
        
        price = prices[0]
        
        return {
            "success": True,
            "figi": price.get("figi"),
            "price": float(price.get("price", {}).get("units", 0)),
            "updated_at": price.get("time")
        }
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_orderbook(figi: str, depth: int = 10) -> Dict[str, Any]:
    """
    Get orderbook (bid/ask quotes).
    
    Args:
        figi: Instrument FIGI
        depth: Number of price levels
        
    Returns:
        Orderbook with bids and asks
    """
    try:
        client = get_client()
        orderbook = client.get_orderbook(figi, depth)
        
        bids = []
        asks = []
        
        for bid in orderbook.get("bids", []):
            bids.append({
                "price": float(bid.get("price", {}).get("units", 0)),
                "quantity": int(bid.get("quantity", 0))
            })
        
        for ask in orderbook.get("asks", []):
            asks.append({
                "price": float(ask.get("price", {}).get("units", 0)),
                "quantity": int(ask.get("quantity", 0))
            })
        
        return {
            "success": True,
            "figi": orderbook.get("figi"),
            "depth": orderbook.get("depth"),
            "bids": bids,
            "asks": asks,
            "last_price": float(orderbook.get("lastPrice", {}).get("units", 0)) if orderbook.get("lastPrice") else None,
            "close_price": float(orderbook.get("closePrice", {}).get("units", 0)) if orderbook.get("closePrice") else None
        }
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_trading_status(figi: str) -> Dict[str, Any]:
    """
    Get trading status for instrument.
    
    Args:
        figi: Instrument FIGI
        
    Returns:
        Trading status information
    """
    try:
        client = get_client()
        status = client.get_trading_status(figi)
        
        return {
            "success": True,
            "figi": status.get("figi"),
            "status": status.get("status"),
            "is_trading_available": status.get("isTradingAvailable"),
            "is_buy_available": status.get("isBuyAvailable"),
            "is_sell_available": status.get("isSellAvailable"),
            "is_limit_orders_available": status.get("limitOrderAvailable"),
            "is_market_orders_available": status.get("marketOrderAvailable")
        }
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# Instrument Info Tools
# =============================================================================

async def get_accounts() -> Dict[str, Any]:
    """
    Get list of broker accounts.
    
    Returns:
        List of accounts
    """
    try:
        client = get_client()
        accounts = client.get_accounts()
        
        return {
            "success": True,
            "accounts": [
                {
                    "id": acc.get("id"),
                    "name": acc.get("name"),
                    "type": acc.get("type"),
                    "status": acc.get("status")
                }
                for acc in accounts
            ]
        }
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_instrument_info(figi: str) -> Dict[str, Any]:
    """
    Get detailed instrument information.
    
    Args:
        figi: Instrument FIGI
        
    Returns:
        Instrument details
    """
    try:
        client = get_client()
        instrument = client.get_instrument_by_figi(figi)
        
        return {
            "success": True,
            "figi": instrument.get("figi"),
            "ticker": instrument.get("ticker"),
            "name": instrument.get("name"),
            "type": instrument.get("instrumentType"),
            "currency": instrument.get("currency"),
            "lot": int(instrument.get("lot", 1)),
            "min_price_increment": float(instrument.get("minPriceIncrement", {}).get("units", 0)) if instrument.get("minPriceIncrement") else None,
            "is_tradable": instrument.get("isTracked", False)
        }
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def search_instrument(ticker: str, instrument_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Search instrument by ticker.
    
    Args:
        ticker: Instrument ticker (e.g., "SBER", "AAPL")
        instrument_type: Optional filter (Stock, Bond, Etf)
        
    Returns:
        List of matching instruments
    """
    try:
        client = get_client()
        instruments = client.search_instrument(ticker, instrument_type)
        
        return {
            "success": True,
            "ticker": ticker,
            "results": [
                {
                    "figi": inst.get("figi"),
                    "ticker": inst.get("ticker"),
                    "name": inst.get("name"),
                    "type": inst.get("instrumentType"),
                    "currency": inst.get("currency")
                }
                for inst in instruments
            ]
        }
    except TinkoffAPIError as e:
        return {"success": False, "error": e.message}
    except Exception as e:
        return {"success": False, "error": str(e)}
