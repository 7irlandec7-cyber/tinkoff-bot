"""
Order Book Scalping Strategy - Скальпинг по стакану
"""
import logging
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime
from collections import deque
import statistics

from .scalping_strategy import SignalType, ScalpSignal

logger = logging.getLogger(__name__)


class OrderBookScalpingStrategy:
    """
    Стратегия скальпинга по стакану (Order Book / Level 2).
    
    Анализирует:
    - Bid/Ask объёмы и их соотношение
    - Дисбаланс ордеров (Order Flow Imbalance)
    - Weighted Mid Price (взвешенная средняя цена)
    - Спред между лучшим бидом и аском
    - Изменение объёмов во времени
    
    Параметры:
    - depth: глубина стакана для анализа
    - imbalance_threshold: порог дисбаланса (0.3 = 30% больше на одной стороне)
    - spread_max: максимальный спред в % для входа
    - volume_boost: минимальное превышение объёма для подтверждения
    """
    
    def __init__(
        self,
        depth: int = 20,
        imbalance_threshold: float = 0.3,
        spread_max_percent: float = 0.5,
        volume_boost: float = 1.3,
        min_history: int = 3,
    ):
        self.depth = depth
        self.imbalance_threshold = imbalance_threshold
        self.spread_max_percent = spread_max_percent
        self.volume_boost = volume_boost
        self.min_history = min_history
        
        # История для сглаживания
        self.imbalance_history: Dict[str, deque] = {}
        self.spread_history: Dict[str, deque] = {}
        self.mid_price_history: Dict[str, deque] = {}
        
        logger.info(
            f"📊 OrderBook стратегия: depth={depth}, imbalance={imbalance_threshold}, "
            f"spread_max={spread_max_percent}%"
        )
    
    def _parse_orderbook(self, orderbook: Dict) -> Optional[Dict]:
        """Парсинг стакана из API ответа."""
        if not orderbook:
            return None
        
        bids = []
        asks = []
        
        for bid in orderbook.get("bids", []):
            price = float(bid.get("price", 0))
            quantity = int(bid.get("quantity", 0))
            if price > 0 and quantity > 0:
                bids.append({"price": price, "quantity": quantity})
        
        for ask in orderbook.get("asks", []):
            price = float(ask.get("price", 0))
            quantity = int(ask.get("quantity", 0))
            if price > 0 and quantity > 0:
                asks.append({"price": price, "quantity": quantity})
        
        if not bids or not asks:
            return None
        
        # Лучшие цены
        best_bid = bids[0]["price"]
        best_ask = asks[0]["price"]
        
        # Спред
        spread = (best_ask - best_bid) / best_bid * 100 if best_bid > 0 else 0
        
        # Weighted Mid Price
        total_bid_vol = sum(b["quantity"] for b in bids[:5])
        total_ask_vol = sum(a["quantity"] for a in asks[:5])
        mid_price = (best_bid + best_ask) / 2
        
        if total_bid_vol + total_ask_vol > 0:
            weighted_mid = (best_bid * total_ask_vol + best_ask * total_bid_vol) / (total_bid_vol + total_ask_vol)
        else:
            weighted_mid = mid_price
        
        # Общие объёмы
        total_bid_qty = sum(b["quantity"] for b in bids)
        total_ask_qty = sum(a["quantity"] for a in asks)
        
        # Дисбаланс: (bid - ask) / (bid + ask)
        total_vol = total_bid_qty + total_ask_qty
        imbalance = (total_bid_qty - total_ask_qty) / total_vol if total_vol > 0 else 0
        
        # Дисбаланс по первым уровням
        top_bid_qty = sum(b["quantity"] for b in bids[:5])
        top_ask_qty = sum(a["quantity"] for a in asks[:5])
        top_imbalance = (top_bid_qty - top_ask_qty) / (top_bid_qty + top_ask_qty) if (top_bid_qty + top_ask_qty) > 0 else 0
        
        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "mid_price": mid_price,
            "weighted_mid": weighted_mid,
            "total_bid_qty": total_bid_qty,
            "total_ask_qty": total_ask_qty,
            "top_bid_qty": top_bid_qty,
            "top_ask_qty": top_ask_qty,
            "imbalance": imbalance,
            "top_imbalance": top_imbalance,
            "bids": bids,
            "asks": asks,
        }
    
    def _get_imbalance_history(self, figi: str) -> deque:
        if figi not in self.imbalance_history:
            self.imbalance_history[figi] = deque(maxlen=10)
        return self.imbalance_history[figi]
    
    def _get_spread_history(self, figi: str) -> deque:
        if figi not in self.spread_history:
            self.spread_history[figi] = deque(maxlen=10)
        return self.spread_history[figi]
    
    def _get_mid_history(self, figi: str) -> deque:
        if figi not in self.mid_price_history:
            self.mid_price_history[figi] = deque(maxlen=20)
        return self.mid_price_history[figi]
    
    def analyze(
        self,
        figi: str,
        ticker: str,
        current_price: float,
        volume: float = 0,
        orderbook: Optional[Dict] = None,
    ) -> ScalpSignal:
        """
        Анализировать инструмент по стакану.
        
        Args:
            figi: FIGI код
            ticker: Тикер
            current_price: Текущая цена (fallback)
            volume: Объём (опционально)
            orderbook: Данные стакана (опционально, получить через get_orderbook)
        
        Returns:
            ScalpSignal
        """
        if not orderbook:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason="Нет данных стакана",
                indicators={}
            )
        
        # Парсим стакан
        ob_data = self._parse_orderbook(orderbook)
        if not ob_data:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason="Пустой стакан",
                indicators={}
            )
        
        # Добавляем в историю
        imbalance_hist = self._get_imbalance_history(figi)
        spread_hist = self._get_spread_history(figi)
        mid_hist = self._get_mid_history(figi)
        
        imbalance_hist.append(ob_data["imbalance"])
        spread_hist.append(ob_data["spread"])
        mid_hist.append(ob_data["mid_price"])
        
        # Индикаторы
        indicators = {
            "imbalance": ob_data["imbalance"],
            "top_imbalance": ob_data["top_imbalance"],
            "spread": ob_data["spread"],
            "weighted_mid": ob_data["weighted_mid"],
            "bid_qty": ob_data["total_bid_qty"],
            "ask_qty": ob_data["total_ask_qty"],
        }
        
        # Недостаточно данных
        if len(imbalance_hist) < self.min_history:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason=f"История накопления ({len(imbalance_hist)}/{self.min_history})",
                indicators=indicators
            )
        
        # Проверка спреда
        if ob_data["spread"] > self.spread_max_percent:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.2,
                reason=f"Широкий спред: {ob_data['spread']:.2f}%",
                indicators=indicators
            )
        
        # Тренд дисбаланса
        avg_imbalance = statistics.mean(list(imbalance_hist))
        imbalance_change = ob_data["imbalance"] - avg_imbalance
        
        # Изменение цены mid за период
        mid_price_change = 0
        if len(mid_hist) >= 3:
            first_mid = list(mid_hist)[0]
            last_mid = list(mid_hist)[-1]
            mid_price_change = (last_mid - first_mid) / first_mid * 100 if first_mid > 0 else 0
        
        signal_type = SignalType.HOLD
        confidence = 0.0
        reason = ""
        
        # BUY: Сильный дисбаланс на покупку + растёт
        if ob_data["imbalance"] > self.imbalance_threshold:
            if imbalance_change > 0.05:  # Растёт
                # Сила сигнала
                strength = min(abs(ob_data["imbalance"]) / 0.5, 1.0)
                trend_boost = 1.2 if mid_price_change > 0 else 1.0
                
                confidence = min(0.6 + strength * 0.3 * trend_boost, 0.95)
                signal_type = SignalType.BUY
                reason = f"Strong bid imbalance: {ob_data['imbalance']:.1%} (change: {imbalance_change:+.1%})"
                
                indicators["signal_reason"] = "bid_imbalance"
        
        # SELL: Сильный дисбаланс на продажу + падает
        elif ob_data["imbalance"] < -self.imbalance_threshold:
            if imbalance_change < -0.05:  # Падает
                strength = min(abs(ob_data["imbalance"]) / 0.5, 1.0)
                trend_boost = 1.2 if mid_price_change < 0 else 1.0
                
                confidence = min(0.6 + strength * 0.3 * trend_boost, 0.95)
                signal_type = SignalType.SELL
                reason = f"Strong ask imbalance: {ob_data['imbalance']:.1%} (change: {imbalance_change:+.1%})"
                
                indicators["signal_reason"] = "ask_imbalance"
        
        # Контр-трендовая проверка: если дисбаланс резко изменился
        if signal_type == SignalType.HOLD:
            # Резкий сдвиг дисбаланса может указывать на разворот
            if abs(imbalance_change) > 0.15:
                if ob_data["imbalance"] > 0.2:
                    # Резкий сдвиг вверх - возможно ловушка
                    signal_type = SignalType.SELL
                    confidence = 0.5
                    reason = f"Counter-trend: sudden bid spike"
                elif ob_data["imbalance"] < -0.2:
                    signal_type = SignalType.BUY
                    confidence = 0.5
                    reason = f"Counter-trend: sudden ask spike"
        
        if signal_type == SignalType.HOLD:
            reason = f"Imbalance: {ob_data['imbalance']:.1%}, spread: {ob_data['spread']:.2f}%"
        
        return ScalpSignal(
            signal_type=signal_type,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=confidence,
            reason=reason,
            indicators=indicators
        )
    
    def reset(self, figi: str):
        """Сбросить историю для инструмента."""
        for hist_dict in [self.imbalance_history, self.spread_history, self.mid_price_history]:
            if figi in hist_dict:
                del hist_dict[figi]
    
    def should_close_position(
        self,
        figi: str,
        entry_price: float,
        current_price: float,
        direction: str,
        take_profit: float = 0.8,
        stop_loss: float = 0.5
    ) -> tuple:
        """
        Проверить, нужно ли закрыть позицию.
        
        Returns:
            (should_close: bool, reason: str)
        """
        if entry_price <= 0 or current_price <= 0:
            return False, ""
        
        pnl_percent = (current_price - entry_price) / entry_price * 100
        
        if direction == "SELL":
            if pnl_percent > stop_loss:
                return True, f"Стоп-лосс: {pnl_percent:.2f}%"
            if pnl_percent < -take_profit:
                return True, f"Тейк-профит: {pnl_percent:.2f}%"
        else:
            if pnl_percent < -stop_loss:
                return True, f"Стоп-лосс: {pnl_percent:.2f}%"
            if pnl_percent > take_profit:
                return True, f"Тейк-профит: {pnl_percent:.2f}%"
        
        return False, ""


def get_orderbook_strategy() -> OrderBookScalpingStrategy:
    """Получить экземпляр OrderBook стратегии."""
    return OrderBookScalpingStrategy(
        depth=20,
        imbalance_threshold=0.3,  # 30% больше на одной стороне
        spread_max_percent=0.5,    # Макс 0.5% спред
        volume_boost=1.3,
        min_history=3,
    )
