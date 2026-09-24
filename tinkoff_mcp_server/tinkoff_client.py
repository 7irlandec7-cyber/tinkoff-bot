"""
Tinkoff MCP Server - Tinkoff API Client Module
Uses requests for API calls
"""
import logging
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, date

# urllib3 есть в venv проекта, но может отсутствовать в системном окружении.
# Отключение InsecureRequestWarning не критично для работы клиента.
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    pass

logger = logging.getLogger(__name__)


class TinkoffClient:
    """Client for Tinkoff Invest API v2."""

    def __init__(self, token: str, account_id: Optional[str] = None):
        self.token = token
        self.account_id = account_id
        self.base_url = "https://invest-public-api.tinkoff.ru/rest"

    def _request(self, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make request using requests."""
        url = f"{self.base_url}/{endpoint}"

        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json"
                },
                json=data or {},
                verify=False,
                timeout=30
            )
            return response.json()
        except Exception as e:
            logger.error(f"API error: {e}")
            return {}

    def get_accounts(self) -> List[Dict[str, Any]]:
        """Get list of broker accounts."""
        data = self._request("tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts")
        return data.get("accounts", [])

    def get_default_account(self) -> str:
        """Get default account ID."""
        if self.account_id:
            return self.account_id

        accounts = self.get_accounts()
        if not accounts:
            raise TinkoffAPIError("No accounts found", {})

        for acc in accounts:
            if acc.get("type") == "ACCOUNT_TYPE_TINKOFF":
                return acc["id"]

        return accounts[0]["id"]

    def get_portfolio(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Get portfolio holdings."""
        acc_id = account_id or self.get_default_account()
        return self._request(
            "tinkoff.public.invest.api.contract.v1.PortfolioService/GetPortfolio",
            {"accountId": acc_id}
        )

    def get_portfolio_currencies(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Get portfolio currencies."""
        acc_id = account_id or self.get_default_account()
        return self._request(
            "tinkoff.public.invest.api.contract.v1.PortfolioService/GetPortfolioCurrencies",
            {"accountId": acc_id}
        )

    def get_positions(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Get open positions."""
        acc_id = account_id or self.get_default_account()
        return self._request(
            "tinkoff.public.invest.api.contract.v1.OperationsService/GetPositions",
            {"accountId": acc_id}
        )

    def get_orders(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get open orders."""
        acc_id = account_id or self.get_default_account()
        data = self._request(
            "tinkoff.public.invest.api.contract.v1.OrdersService/GetOrders",
            {"accountId": acc_id}
        )
        return data.get("orders", [])

    def get_orderbook(self, figi: str, depth: int = 20) -> Dict[str, Any]:
        """
        Get order book (стакан) для инструмента.

        Args:
            figi: FIGI код инструмента
            depth: Глубина стакана (количество уровней)

        Returns:
            Dict с bids, asks и другими данными стакана
        """
        return self._request(
            "tinkoff.public.invest.api.contract.v1.MarketDataService/GetOrderBook",
            {"figi": figi, "depth": depth}
        )

    def place_market_order(
        self,
        figi: str,
        quantity: int,
        direction: str,
        price: float,
        account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Place MARKET order for instant execution."""
        acc_id = account_id or self.get_default_account()

        # Используем ORDER_DIRECTION_BUY/SELL (строковый формат)
        api_direction = "ORDER_DIRECTION_BUY" if direction == "BUY" else "ORDER_DIRECTION_SELL"

        logger.info(f"MARKET ORDER: figi={figi}, qty={quantity}, dir={direction}")

        result = self._request(
            "tinkoff.public.invest.api.contract.v1.OrdersService/PostOrder",
            {
                "accountId": acc_id,
                "figi": figi,
                "quantity": quantity,
                "direction": api_direction,
                "orderType": "ORDER_TYPE_MARKET",
            }
        )

        # Если market order отклонён (order_type invalid) - пробуем лимитку по текущей цене
        if result.get("code") in [3, 30083] or "order_type" in str(result.get("message", "")).lower():
            logger.warning(f"Market order rejected, trying LIMIT order for {figi}")
            # Получаем текущую цену
            try:
                ob = self.get_orderbook(figi, 1)
                if direction == "BUY":
                    price_data = ob.get('asks', [{}])[0].get('price', {})
                else:
                    price_data = ob.get('bids', [{}])[0].get('price', {})
                if isinstance(price_data, dict):
                    price_val = float(price_data.get('units', 0)) + float(price_data.get('nano', 0)) / 1e9
                else:
                    price_val = float(price_data)
                return self.place_limit_order(figi, quantity, direction, price_val, account_id)
            except Exception as e:
                logger.error(f"Failed to get price for limit fallback: {e}")

        return result

    def place_limit_order(
        self,
        figi: str,
        quantity: int,
        direction: str,
        price: float,
        account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Place limit order using PostOrder (PostLimitOrder may not work)."""
        acc_id = account_id or self.get_default_account()
        api_direction = "ORDER_DIRECTION_BUY" if direction == "BUY" else "ORDER_DIRECTION_SELL"

        # Цена в формате Units/Nano
        price_units = int(price)
        price_nano = int((price - price_units) * 1e9)

        logger.info(f"LIMIT ORDER: figi={figi}, qty={quantity}, dir={direction}, price={price} -> units={price_units}, nano={price_nano}")

        # Используем PostOrder с order_type=LIMIT
        return self._request(
            "tinkoff.public.invest.api.contract.v1.OrdersService/PostOrder",
            {
                "accountId": acc_id,
                "figi": figi,
                "quantity": quantity,
                "direction": api_direction,
                "orderType": "ORDER_TYPE_LIMIT",
                "price": {"units": price_units, "nano": price_nano}
            }
        )

    def place_stop_loss_order(
        self,
        figi: str,
        quantity: int,
        stop_price: float,
        direction: Optional[str] = None,
        account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Place exchange stop-loss order.

        Этот ордер находится на бирже и сработает ДАЖЕ если бот не работает.
        direction: None = auto-detect (для BUY позиции -> SELL SL, для SELL -> BUY SL).
                  Можно указать явно 'BUY' или 'SELL'.

        Использует StopOrdersService/PostStopOrder (не OrdersService/PostOrder).
        """
        acc_id = account_id or self.get_default_account()

        # Auto-detect direction
        if direction is None:
            positions = self.get_positions()
            for s in positions.get('securities', []):
                if s.get('figi') == figi:
                    balance = int(s.get('balance', 0))
                    # Если баланс > 0 - это LONG позиция, SL = SELL
                    if balance > 0:
                        direction = "SELL"
                    else:
                        direction = "BUY"
                    break
            if direction is None:
                direction = "SELL"  # default

        api_direction = "STOP_ORDER_DIRECTION_BUY" if direction == "BUY" else "STOP_ORDER_DIRECTION_SELL"
        price_units = int(stop_price)
        price_nano = int((stop_price - price_units) * 1e9)

        logger.info(f"EXCHANGE STOP-LOSS: figi={figi}, qty={quantity}, dir={direction}, stop_price={stop_price}")

        return self._request(
            "tinkoff.public.invest.api.contract.v1.StopOrdersService/PostStopOrder",
            {
                "accountId": acc_id,
                "figi": figi,
                "quantity": quantity,
                "direction": api_direction,
                "stopPrice": {"units": price_units, "nano": price_nano},
                "expirationType": "STOP_ORDER_EXPIRATION_TYPE_GOOD_TILL_CANCEL",
                "stopOrderType": "STOP_ORDER_TYPE_STOP_LOSS",
            }
        )

    def cancel_order(self, order_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Cancel an order."""
        acc_id = account_id or self.get_default_account()
        return self._request(
            "tinkoff.public.invest.api.contract.v1.OrdersService/CancelOrder",
            {"accountId": acc_id, "orderId": order_id}
        )

    def cancel_stop_order(self, stop_order_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Cancel an exchange STOP order (StopOrdersService/CancelStopOrder).

        Используется чтобы убрать страховочный SL перед программным закрытием позиции
        и не оставить «сиротский» стоп, который продаст бумаги повторно.
        """
        acc_id = account_id or self.get_default_account()
        return self._request(
            "tinkoff.public.invest.api.contract.v1.StopOrdersService/CancelStopOrder",
            {"accountId": acc_id, "stopOrderId": stop_order_id}
        )

    def get_stop_orders(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all active exchange stop orders for the account."""
        acc_id = account_id or self.get_default_account()
        data = self._request(
            "tinkoff.public.invest.api.contract.v1.StopOrdersService/GetStopOrders",
            {"accountId": acc_id}
        )
        return data.get("stopOrders", [])

    def search_instrument(self, ticker: str, instrument_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search instrument by ticker."""
        data = self._request(
            "tinkoff.public.invest.api.contract.v1.InstrumentsService/SearchByTicker",
            {"ticker": ticker}
        )
        instruments = data.get("instruments", [])
        if instrument_type:
            instruments = [i for i in instruments if i.get("instrumentType") == instrument_type]
        return instruments

    def get_last_prices(self, figi_list: List[str]) -> List[Dict[str, Any]]:
        """Get last prices."""
        data = self._request(
            "tinkoff.public.invest.api.contract.v1.MarketDataService/GetLastPrices",
            {"figi": figi_list}
        )
        return data.get("lastPrices", [])

    def get_instrument_by_figi(self, figi: str) -> Dict[str, Any]:
        """Get instrument info by FIGI."""
        return self._request(
            "tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy",
            {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": figi}
        )

    def get_operations(
        self,
        from_date: date,
        to_date: date,
        account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get operations history."""
        acc_id = account_id or self.get_default_account()
        return self._request(
            "tinkoff.public.invest.api.contract.v1.OperationsService/GetOperations",
            {
                "accountId": acc_id,
                "from": from_date.isoformat() + "T00:00:00Z",
                "to": to_date.isoformat() + "T23:59:59Z"
            }
        )

    def get_candles(
        self,
        figi: str,
        from_time: datetime,
        to_time: datetime,
        interval: str = "1min"
    ) -> List[Dict[str, Any]]:
        """Get historical candles."""
        data = self._request(
            "tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles",
            {
                "figi": figi,
                "from": from_time.isoformat() + "Z",
                "to": to_time.isoformat() + "Z",
                "interval": interval
            }
        )
        return data.get("candles", [])


class TinkoffAPIError(Exception):
    """Exception for Tinkoff API errors."""

    def __init__(self, message: str, details: Dict[str, Any]):
        self.message = message
        self.details = details
        super().__init__(f"Tinkoff API Error: {message}")
