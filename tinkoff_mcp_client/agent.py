"""
Tinkoff MCP Client - Trading Agent
"""
import logging
import sys
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from .strategies import (
    BaseStrategy,
    MomentumStrategy,
    TrendFollowingStrategy,
    MeanReversionStrategy,
)
from .strategies.base import Signal, Candle, Position

logger = logging.getLogger(__name__)


# Strategy registry
STRATEGIES: Dict[str, type] = {
    "momentum": MomentumStrategy,
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
}


@dataclass
class AgentConfig:
    """Configuration for trading agent."""
    strategy: str = "trend_following"
    tickers: List[str] = field(default_factory=lambda: ["SBER", "GAZP", "VTBR"])
    dry_run: bool = True
    check_interval: int = 60  # seconds
    max_position_size: float = 10000.0
    min_confidence: float = 0.6
    token: str = ""
    account_id: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        """Create config from dictionary."""
        known_fields = {
            "strategy", "tickers", "dry_run",
            "check_interval", "max_position_size", "min_confidence",
            "token", "account_id"
        }
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


@dataclass
class TradeDecision:
    """Record of a trading decision."""
    timestamp: datetime
    ticker: str
    action: str  # "BUY", "SELL", "HOLD"
    signal: Optional[Signal] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    executed: bool = False
    dry_run: bool = True


class TinkoffAPIError(Exception):
    """Exception for Tinkoff API errors."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(f"Tinkoff API Error: {message}")


class TinkoffTradingClient:
    """
    Real Tinkoff Invest API v2 client.
    
    Connects directly to Tinkoff Invest REST API.
    """
    
    BASE_URL = "https://invest-public-api.tinkoff.ru/rest"
    
    def __init__(self, token: str, account_id: Optional[str] = None):
        """
        Initialize Tinkoff API client.
        
        Args:
            token: Tinkoff API token
            account_id: Optional specific account ID
        """
        self.token = token
        self.account_id = account_id
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self._accounts_cache: Optional[List[Dict]] = None
        self._default_account_id: Optional[str] = None
        self.logger = logging.getLogger(f"{__name__}.TinkoffTradingClient")
    
    def _post(self, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make POST request to Tinkoff API."""
        import httpx
        
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        
        try:
            with httpx.Client(timeout=30.0, verify=False) as client:
                response = client.post(url, headers=self.headers, json=data or {})
                response.raise_for_status()
                
                if not response.text:
                    return {}
                
                result = response.json()
                
                # Check for API errors
                if result.get("status") == "Error":
                    error = result.get("payload", result)
                    raise TinkoffAPIError(error.get("message", "Unknown error"), error)
                
                # Check for gRPC-style error
                if result.get("code", 0) != 0 and result.get("message"):
                    raise TinkoffAPIError(result.get("message", "API error"), result)
                
                return result
                
        except httpx.HTTPStatusError as e:
            raise TinkoffAPIError(f"HTTP error: {e.response.status_code}", {"response": str(e)})
        except Exception as e:
            raise TinkoffAPIError(f"Request failed: {e}", {"error": str(e)})
    
    def _get_default_account(self) -> str:
        """Get default account ID."""
        if self.account_id:
            return self.account_id
        
        if self._default_account_id is None:
            data = self._post("/tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts")
            accounts = data.get("accounts", [])
            
            if not accounts:
                raise TinkoffAPIError("No accounts found", {})
            
            # Prefer TINKOFF account type
            for acc in accounts:
                if acc.get("type") == "ACCOUNT_TYPE_TINKOFF":
                    self._default_account_id = acc["id"]
                    self._accounts_cache = accounts
                    return self._default_account_id
            
            # Fallback to first account
            self._default_account_id = accounts[0]["id"]
            self._accounts_cache = accounts
        
        return self._default_account_id
    
    @staticmethod
    def _parse_price(price_data: Dict) -> float:
        """Parse price from Tinkoff API format."""
        if not price_data:
            return 0.0
        units = int(price_data.get("units", 0))
        nano = int(price_data.get("nano", 0))
        return units + nano / 1e9
    
    @staticmethod
    def _parse_quantity(qty_data: Dict) -> int:
        """Parse quantity from Tinkoff API format."""
        if not qty_data:
            return 0
        return int(qty_data.get("units", 0))
    
    # =============================================================================
    # Market Data Methods
    # =============================================================================
    
    def get_last_prices(self, figi_list: List[str]) -> List[Dict[str, Any]]:
        """Get last prices for instruments."""
        data = self._post("/tinkoff.public.invest.api.contract.v1.MarketDataService/GetLastPrices", {
            "figi": figi_list
        })
        prices = data.get("lastPrices", [])
        
        result = []
        for p in prices:
            result.append({
                "figi": p.get("figi"),
                "ticker": p.get("ticker"),
                "price": self._parse_price(p.get("price")),
                "time": p.get("time")
            })
        
        return result
    
    def get_orderbook(self, figi: str, depth: int = 10) -> Dict[str, Any]:
        """Get orderbook for instrument."""
        data = self._post("/tinkoff.public.invest.api.contract.v1.MarketDataService/GetOrderBook", {
            "figi": figi,
            "depth": depth
        })
        
        return {
            "figi": data.get("figi"),
            "bids": [{"price": self._parse_price(b.get("price")), "quantity": int(b.get("quantity", 0))} 
                     for b in data.get("bids", [])],
            "asks": [{"price": self._parse_price(a.get("price")), "quantity": int(a.get("quantity", 0))} 
                     for a in data.get("asks", [])],
            "last_price": self._parse_price(data.get("lastPrice"))
        }
    
    def get_trading_status(self, figi: str) -> Dict[str, Any]:
        """Get trading status for instrument."""
        data = self._post("/tinkoff.public.invest.api.contract.v1.MarketDataService/GetTradingStatus", {
            "figi": figi
        })
        
        return {
            "figi": data.get("figi"),
            "status": data.get("tradingStatus"),
            "is_trading_available": data.get("tradingStatus") == "SECURITY_TRADING_STATUS_NORMAL_TRADING",
            "is_buy_available": data.get("marketOrderAvailableFlag", False),
            "is_sell_available": data.get("marketOrderAvailableFlag", False)
        }
    
    def get_candles(
        self,
        figi: str,
        from_time: datetime,
        to_time: datetime,
        interval: str = "hour"
    ) -> List[Dict[str, Any]]:
        """Get historical candles."""
        interval_map = {
            "1min": "CANDLE_INTERVAL_1_MIN",
            "5min": "CANDLE_INTERVAL_5_MIN",
            "15min": "CANDLE_INTERVAL_15_MIN",
            "hour": "CANDLE_INTERVAL_HOUR",
            "day": "CANDLE_INTERVAL_DAY",
            "week": "CANDLE_INTERVAL_WEEK"
        }
        api_interval = interval_map.get(interval, "CANDLE_INTERVAL_DAY")
        
        data = self._post("/tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles", {
            "figi": figi,
            "from": from_time.isoformat() + "Z",
            "to": to_time.isoformat() + "Z",
            "interval": api_interval
        })
        
        candles = data.get("candles", [])
        result = []
        
        for c in candles:
            result.append({
                "time": c.get("time"),
                "open": self._parse_price(c.get("open")),
                "high": self._parse_price(c.get("high")),
                "low": self._parse_price(c.get("low")),
                "close": self._parse_price(c.get("close")),
                "volume": int(c.get("volume", 0))
            })
        
        return result
    
    # =============================================================================
    # Instrument Methods
    # =============================================================================
    
    def get_instrument_info(self, figi: str) -> Dict[str, Any]:
        """Get instrument info by FIGI."""
        data = self._post("/tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy", {
            "idType": "INSTRUMENT_ID_TYPE_FIGI",
            "id": figi
        })
        
        return {
            "figi": data.get("figi"),
            "ticker": data.get("ticker"),
            "name": data.get("name"),
            "type": data.get("instrumentType"),
            "currency": data.get("currency"),
            "lot": int(data.get("lot", 1))
        }
    
    def get_shares(self) -> List[Dict[str, Any]]:
        """Get all shares."""
        data = self._post("/tinkoff.public.invest.api.contract.v1.InstrumentsService/Shares", {})
        instruments = data.get("instruments", [])
        
        result = []
        for inst in instruments:
            result.append({
                "figi": inst.get("figi"),
                "ticker": inst.get("ticker"),
                "name": inst.get("name"),
                "type": inst.get("instrumentType"),
                "currency": inst.get("currency")
            })
        
        return result
    
    def search_instrument(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Search instrument by ticker - returns first match."""
        shares = self.get_shares()
        
        for share in shares:
            if share.get("ticker", "").upper() == ticker.upper():
                return share
        
        return None
    
    # =============================================================================
    # Portfolio Methods
    # =============================================================================
    
    def get_portfolio(self) -> Dict[str, Any]:
        """Get portfolio holdings."""
        account_id = self._get_default_account()
        
        try:
            data = self._post("/tinkoff.public.invest.api.contract.v1.PortfolioService/GetPortfolio", {
                "accountId": account_id
            })
            return data.get("positions", [])
        except TinkoffAPIError as e:
            # Portfolio might return 404 if empty or no access
            self.logger.warning(f"Could not get portfolio: {e.message}")
            return []
    
    def get_portfolio_currencies(self) -> List[Dict[str, Any]]:
        """Get portfolio currencies."""
        account_id = self._get_default_account()
        
        try:
            data = self._post("/tinkoff.public.invest.api.contract.v1.PortfolioService/GetPortfolioCurrencies", {
                "accountId": account_id
            })
            currencies = data.get("currencies", [])
            
            result = []
            for c in currencies:
                result.append({
                    "currency": c.get("currency"),
                    "balance": self._parse_price(c.get("balance")),
                    "blocked": self._parse_price(c.get("blocked"))
                })
            
            return result
        except TinkoffAPIError as e:
            self.logger.warning(f"Could not get currencies: {e.message}")
            return []
    
    # =============================================================================
    # Order Methods
    # =============================================================================
    
    def get_orders(self) -> List[Dict[str, Any]]:
        """Get open orders."""
        account_id = self._get_default_account()
        
        data = self._post("/tinkoff.public.invest.api.contract.v1.OrdersService/GetOrders", {
            "accountId": account_id
        })
        
        orders = data.get("orders", [])
        result = []
        
        for order in orders:
            result.append({
                "order_id": order.get("orderId"),
                "figi": order.get("figi"),
                "direction": order.get("direction"),
                "status": order.get("status"),
                "requested_lots": self._parse_quantity(order.get("requestedLots")),
                "executed_lots": self._parse_quantity(order.get("executedLots")),
                "price": self._parse_price(order.get("price")) if order.get("price") else None,
                "created_at": order.get("createdAt")
            })
        
        return result
    
    def place_market_order(
        self,
        figi: str,
        quantity: int,
        direction: str  # "BUY" or "SELL"
    ) -> Dict[str, Any]:
        """Place market order."""
        account_id = self._get_default_account()
        
        return self._post("/tinkoff.public.invest.api.contract.v1.OrdersService/PostMarketOrder", {
            "accountId": account_id,
            "figi": figi,
            "quantity": quantity,
            "direction": direction
        })
    
    def place_limit_order(
        self,
        figi: str,
        quantity: int,
        direction: str,
        price: float
    ) -> Dict[str, Any]:
        """Place limit order."""
        account_id = self._get_default_account()
        
        # Convert price to units + nano format
        units = int(price)
        nano = int((price - units) * 1e9)
        
        return self._post("/tinkoff.public.invest.api.contract.v1.OrdersService/PostLimitOrder", {
            "accountId": account_id,
            "figi": figi,
            "quantity": quantity,
            "direction": direction,
            "price": {"units": str(units), "nano": nano}
        })
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an order."""
        account_id = self._get_default_account()
        
        return self._post("/tinkoff.public.invest.api.contract.v1.OrdersService/CancelOrder", {
            "accountId": account_id,
            "orderId": order_id
        })
    
    async def close(self):
        """Close client (no-op for sync client)."""
        pass


# Legacy alias for backwards compatibility
MCPClient = TinkoffTradingClient


class TradingAgent:
    """
    Trading agent that uses Tinkoff API to make trading decisions.
    
    The agent:
    1. Gets portfolio state from Tinkoff API
    2. Analyzes instruments with configured strategy
    3. Generates and executes trading signals
    """
    
    def __init__(
        self,
        config: AgentConfig,
        client: Optional[TinkoffTradingClient] = None
    ):
        """
        Initialize trading agent.
        
        Args:
            config: Agent configuration
            client: Optional Tinkoff client (creates one if not provided)
        """
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.TradingAgent")
        
        # Create client if not provided
        if client is None:
            if not config.token:
                # Try to get token from environment
                config.token = os.environ.get("TINKOFF_TOKEN", "")
            
            if not config.token:
                raise ValueError("TINKOFF_TOKEN is required")
            
            client = TinkoffTradingClient(
                token=config.token,
                account_id=config.account_id
            )
        
        self.client = client
        self.strategy = self._load_strategy()
        self.decisions: List[TradeDecision] = []
    
    def _load_strategy(self) -> BaseStrategy:
        """Load trading strategy from config."""
        strategy_class = STRATEGIES.get(self.config.strategy)
        
        if not strategy_class:
            self.logger.warning(
                f"Unknown strategy '{self.config.strategy}', "
                f"using trend_following"
            )
            strategy_class = TrendFollowingStrategy
        
        self.logger.info(f"Loading strategy: {strategy_class.name}")
        return strategy_class(
            config={
                "min_confidence": self.config.min_confidence,
                "max_position_size": self.config.max_position_size,
            }
        )
    
    async def analyze_instrument(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Analyze a single instrument.
        
        Args:
            ticker: Instrument ticker
            
        Returns:
            Analysis results or None on error
        """
        from datetime import timedelta
        
        try:
            self.logger.info(f"Analyzing {ticker}...")
            
            # Search for instrument
            instrument = self.client.search_instrument(ticker)
            
            if not instrument:
                self.logger.warning(f"No instrument found for {ticker}")
                return None
            
            figi = instrument.get("figi")
            
            if not figi:
                self.logger.warning(f"No FIGI for {ticker}")
                return None
            
            self.logger.info(f"  Found: {instrument.get('name')} ({figi})")
            
            # Get candles for last 60 days
            to_time = datetime.now()
            from_time = to_time - timedelta(days=60)
            
            candles_raw = self.client.get_candles(figi, from_time, to_time, interval="day")
            
            if not candles_raw:
                self.logger.warning(f"No candle data for {ticker}")
                return None
            
            # Convert to Candle objects
            candles = [
                Candle(
                    time=c["time"],
                    open=c["open"],
                    high=c["high"],
                    low=c["low"],
                    close=c["close"],
                    volume=c["volume"]
                )
                for c in candles_raw
            ]
            
            # Get current price
            try:
                prices = self.client.get_last_prices([figi])
                current_price = prices[0]["price"] if prices else candles[-1].close
            except Exception as e:
                self.logger.warning(f"  Could not get live price: {e}")
                current_price = candles[-1].close if candles else 0
            
            # Get trading status
            try:
                status = self.client.get_trading_status(figi)
                is_trading = status.get("is_trading_available", False)
            except:
                is_trading = True
            
            self.logger.info(f"  Current price: {current_price:.2f} RUB")
            self.logger.info(f"  Candles loaded: {len(candles)}")
            self.logger.info(f"  Trading available: {is_trading}")
            
            return {
                "ticker": ticker,
                "figi": figi,
                "instrument": instrument,
                "candles": candles,
                "current_price": current_price,
                "is_trading_available": is_trading
            }
            
        except TinkoffAPIError as e:
            self.logger.error(f"API error analyzing {ticker}: {e.message}")
            return None
        except Exception as e:
            self.logger.error(f"Error analyzing {ticker}: {e}")
            return None
    
    async def get_portfolio_positions(self) -> List[Position]:
        """
        Get current portfolio positions.
        
        Returns:
            List of current positions
        """
        try:
            positions_raw = self.client.get_portfolio()
            positions = []
            
            for pos_data in positions_raw:
                current_value = self.client._parse_price(pos_data.get("currentValue"))
                avg_price = self.client._parse_price(pos_data.get("averagePositionPrice"))
                quantity = self.client._parse_quantity(pos_data.get("quantity"))
                
                positions.append(Position(
                    figi=pos_data.get("figi", ""),
                    ticker=pos_data.get("ticker", ""),
                    name=pos_data.get("name", ""),
                    quantity=quantity,
                    average_price=avg_price,
                    current_value=current_value,
                    profit=current_value - (avg_price * quantity),
                    profit_percent=((current_value - avg_price * quantity) / (avg_price * quantity) * 100) if avg_price > 0 else 0
                ))
            
            return positions
            
        except Exception as e:
            self.logger.error(f"Error getting portfolio: {e}")
            return []
    
    async def get_available_cash(self) -> float:
        """Get available cash for trading."""
        try:
            currencies = self.client.get_portfolio_currencies()
            total_rub = 0.0
            
            for cur in currencies:
                if cur.get("currency") == "RUB":
                    total_rub = cur.get("balance", 0) - cur.get("blocked", 0)
                    break
            
            return total_rub
        except Exception as e:
            self.logger.error(f"Error getting cash balance: {e}")
            return 0.0
    
    async def execute_decision(
        self,
        ticker: str,
        figi: str,
        signal: Signal,
        quantity: int
    ) -> bool:
        """
        Execute a trading decision.
        
        Args:
            ticker: Instrument ticker
            figi: Instrument FIGI
            signal: Trading signal
            quantity: Number of lots
            
        Returns:
            True if executed successfully
        """
        try:
            if signal.action == "BUY":
                self.logger.info(f"  Placing BUY order: {quantity} lots of {ticker} @ {signal.price:.2f}")
                
                if self.config.dry_run:
                    self.logger.info(f"  [DRY-RUN] Would place market BUY order")
                    decision = TradeDecision(
                        timestamp=datetime.now(),
                        ticker=ticker,
                        action=signal.action,
                        signal=signal,
                        price=signal.price,
                        quantity=quantity,
                        executed=True,
                        dry_run=True
                    )
                    self.decisions.append(decision)
                    return True
                else:
                    result = self.client.place_market_order(figi, quantity, "BUY")
                    order_id = result.get("orderId", "unknown")
                    self.logger.info(f"  Order placed successfully: {order_id}")
                    decision = TradeDecision(
                        timestamp=datetime.now(),
                        ticker=ticker,
                        action=signal.action,
                        signal=signal,
                        price=signal.price,
                        quantity=quantity,
                        executed=True,
                        dry_run=False
                    )
                    self.decisions.append(decision)
                    return True
                    
            elif signal.action == "SELL":
                self.logger.info(f"  Placing SELL order: {quantity} lots of {ticker} @ {signal.price:.2f}")
                
                if self.config.dry_run:
                    self.logger.info(f"  [DRY-RUN] Would place market SELL order")
                    decision = TradeDecision(
                        timestamp=datetime.now(),
                        ticker=ticker,
                        action=signal.action,
                        signal=signal,
                        price=signal.price,
                        quantity=quantity,
                        executed=True,
                        dry_run=True
                    )
                    self.decisions.append(decision)
                    return True
                else:
                    result = self.client.place_market_order(figi, quantity, "SELL")
                    order_id = result.get("orderId", "unknown")
                    self.logger.info(f"  Order placed successfully: {order_id}")
                    decision = TradeDecision(
                        timestamp=datetime.now(),
                        ticker=ticker,
                        action=signal.action,
                        signal=signal,
                        price=signal.price,
                        quantity=quantity,
                        executed=True,
                        dry_run=False
                    )
                    self.decisions.append(decision)
                    return True
            
            return False
            
        except TinkoffAPIError as e:
            self.logger.error(f"  Order failed: {e.message}")
            return False
        except Exception as e:
            self.logger.error(f"  Order failed: {e}")
            return False
    
    async def run_analysis_cycle(self) -> Dict[str, Any]:
        """
        Run a complete analysis cycle for all tickers.
        
        Returns:
            Summary of analysis results
        """
        self.logger.info("=" * 50)
        self.logger.info("Starting analysis cycle")
        self.logger.info(f"Strategy: {self.strategy.name}")
        self.logger.info(f"Tickers: {self.config.tickers}")
        self.logger.info(f"Mode: {'DRY-RUN' if self.config.dry_run else 'LIVE TRADING'}")
        self.logger.info("=" * 50)
        
        # Get current portfolio
        portfolio = await self.get_portfolio_positions()
        portfolio_by_ticker = {p.ticker: p for p in portfolio}
        self.logger.info(f"Current positions: {len(portfolio)}")
        
        # Show positions
        for pos in portfolio:
            self.logger.info(f"  {pos.ticker}: {pos.quantity} lots @ avg {pos.average_price:.2f} = {pos.current_value:.2f} RUB ({pos.profit_percent:+.2f}%)")
        
        # Get available cash
        available_cash = await self.get_available_cash()
        self.logger.info(f"Available cash: {available_cash:.2f} RUB")
        
        results = {
            "analyzed": 0,
            "signals": [],
            "errors": []
        }
        
        for ticker in self.config.tickers:
            self.logger.info("")
            
            # Analyze instrument
            analysis_data = await self.analyze_instrument(ticker)
            
            if not analysis_data:
                results["errors"].append({"ticker": ticker, "error": "Analysis failed"})
                continue
            
            results["analyzed"] += 1
            candles = analysis_data["candles"]
            current_price = analysis_data["current_price"]
            figi = analysis_data["figi"]
            is_trading = analysis_data.get("is_trading_available", True)
            
            if not is_trading:
                self.logger.warning(f"  Trading not available for {ticker}")
                continue
            
            # Run strategy analysis
            analysis = self.strategy.analyze(candles)
            
            if not analysis.get("valid"):
                self.logger.warning(f"  Invalid analysis: {analysis.get('error')}")
                continue
            
            self.logger.info(f"  Price: {current_price:.2f} RUB")
            if 'trend' in analysis:
                self.logger.info(f"  Trend: {analysis.get('trend')}")
            if 'rsi' in analysis:
                self.logger.info(f"  RSI: {analysis.get('rsi'):.1f}")
            
            # Check for buy signals
            buy_signal = self.strategy.should_buy(
                analysis,
                current_price,
                portfolio
            )
            
            if buy_signal:
                self.logger.info(f"  >>> BUY signal! Confidence: {buy_signal.confidence:.2f}")
                self.logger.info(f"      {buy_signal.reason}")
                
                # Check if we already own this
                if ticker in portfolio_by_ticker:
                    self.logger.info(f"  Already holding {ticker}, skipping buy")
                else:
                    # Calculate position size
                    quantity = self.strategy.calculate_quantity(current_price, available_cash)
                    
                    if quantity > 0:
                        success = await self.execute_decision(ticker, figi, buy_signal, quantity)
                        if success:
                            results["signals"].append({
                                "ticker": ticker,
                                "action": "BUY",
                                "confidence": buy_signal.confidence,
                                "reason": buy_signal.reason,
                                "price": current_price,
                                "quantity": quantity
                            })
                            available_cash -= current_price * quantity
                    else:
                        self.logger.info(f"  Not enough cash for position")
            
            # Check for sell signals on existing positions
            if ticker in portfolio_by_ticker:
                position = portfolio_by_ticker[ticker]
                sell_signal = self.strategy.should_sell(
                    analysis,
                    position,
                    current_price
                )
                
                if sell_signal:
                    self.logger.info(f"  >>> SELL signal! Confidence: {sell_signal.confidence:.2f}")
                    self.logger.info(f"      {sell_signal.reason}")
                    
                    success = await self.execute_decision(ticker, figi, sell_signal, position.quantity)
                    if success:
                        results["signals"].append({
                            "ticker": ticker,
                            "action": "SELL",
                            "confidence": sell_signal.confidence,
                            "reason": sell_signal.reason,
                            "price": current_price,
                            "quantity": position.quantity
                        })
        
        self.logger.info("")
        self.logger.info("=" * 50)
        self.logger.info("Analysis cycle complete")
        self.logger.info(f"Analyzed: {results['analyzed']}")
        self.logger.info(f"Signals: {len(results['signals'])}")
        self.logger.info(f"Errors: {len(results['errors'])}")
        self.logger.info("=" * 50)
        
        return results
    
    def get_decision_history(self) -> List[Dict[str, Any]]:
        """Get history of trading decisions."""
        return [
            {
                "timestamp": d.timestamp.isoformat(),
                "ticker": d.ticker,
                "action": d.action,
                "price": d.price,
                "quantity": d.quantity,
                "executed": d.executed,
                "dry_run": d.dry_run,
                "reason": d.signal.reason if d.signal else None
            }
            for d in self.decisions
        ]
    
    async def close(self):
        """Clean up agent resources."""
        await self.client.close()
