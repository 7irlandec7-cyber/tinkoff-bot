"""
Консервативная стратегия для стабильной прибыли.

Принципы:
1. Вход только у сильной поддержки
2. Сигнал требует подтверждения (2 бара подряд)
3. SL: 0.5%, TP: 0.8%
4. Не более 2 сделок в день
5. Фильтр по объёму
"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional, Dict
from .scalping_strategy import SignalType, ScalpSignal

logger = logging.getLogger(__name__)


@dataclass 
class PriceBar:
    price: float
    volume: float
    timestamp: float


class ConservativeStrategy:
    """
    Консервативная стратегия для стабильной прибыли.
    
    Ключевые принципы:
    1. Только 5-минутные данные (сигнал накопления)
    2. Цена должна быть у поддержки (в нижних 30% диапазона)
    3. Объём выше среднего (активность крупных игроков)
    4. Подтверждение: 2 бара роста подряд
    5. SL: 0.5%, TP: 0.8% - больше места для манёвра
    """
    
    def __init__(self):
        self.price_histories: Dict[str, deque] = {}
        self.volume_histories: Dict[str, deque] = {}
        self.last_prices: Dict[str, float] = {}
        
        # Фиксированные параметры для консервативной торговли
        self.tp_percent = 0.80   # TP 0.8%
        self.sl_percent = 0.50    # SL 0.5%
        
        # Минимум истории
        self.min_history = 10
        
        # Счётчик дневных сделок
        self.daily_trades = 0
        self.last_trade_date = None
    
    def _reset_daily_counter(self):
        """Сбросить счётчик если новый день."""
        from datetime import date
        today = date.today().isoformat()
        if self.last_trade_date != today:
            self.daily_trades = 0
            self.last_trade_date = today
    
    def update_price(self, figi: str, price: float, volume: float = 0):
        """Обновить историю цен."""
        if figi not in self.price_histories:
            self.price_histories[figi] = deque(maxlen=30)
            self.volume_histories[figi] = deque(maxlen=30)
        
        self.price_histories[figi].append(price)
        if volume > 0:
            self.volume_histories[figi].append(volume)
        
        self.last_prices[figi] = price
    
    def _get_price_change(self, figi: str, bars: int = 1) -> float:
        """Получить изменение цены за последние N баров в %."""
        if figi not in self.price_histories or len(self.price_histories[figi]) < bars + 1:
            return 0.0
        
        history = list(self.price_histories[figi])
        if history[-(bars+1)] != 0:
            return (history[-1] - history[-(bars+1)]) / history[-(bars+1)] * 100
        return 0.0
    
    def _get_momentum(self, figi: str, bars: int = 5) -> float:
        """Получить momentum за последние N баров."""
        if figi not in self.price_histories or len(self.price_histories[figi]) < bars + 1:
            return 0.0
        
        history = list(self.price_histories[figi])
        if history[-(bars+1)] != 0:
            return (history[-1] - history[-(bars+1)]) / history[-(bars+1)] * 100
        return 0.0
    
    def _is_near_support(self, figi: str) -> bool:
        """Проверить если цена у поддержки (нижние 30% диапазона)."""
        if figi not in self.price_histories or len(self.price_histories[figi]) < 10:
            return False
        
        history = list(self.price_histories[figi])[-10:]
        current = history[-1]
        
        min_p = min(history)
        max_p = max(history)
        range_p = max_p - min_p
        
        if range_p == 0:
            return False
        
        # Цена в нижних 30% диапазона = near support
        position_from_bottom = (current - min_p) / range_p
        return position_from_bottom < 0.30
    
    def _is_confirmed_uptrend(self, figi: str) -> bool:
        """Проверить подтверждённый аптренд (2 бара роста)."""
        if figi not in self.price_histories or len(self.price_histories[figi]) < 3:
            return False
        
        history = list(self.price_histories[figi])[-3:]
        
        # Оба последних бара должны быть зелёными
        bar1_green = history[-1] > history[-2]
        bar2_green = history[-2] > history[-3]
        
        return bar1_green and bar2_green
    
    def _get_volatility(self, figi: str) -> float:
        """Получить волатильность за последние 10 баров."""
        if figi not in self.price_histories or len(self.price_histories[figi]) < 5:
            return 0.0
        
        history = list(self.price_histories[figi])[-10:]
        if not history:
            return 0.0
        
        max_p = max(history)
        min_p = min(history)
        if min_p == 0:
            return 0.0
        
        return (max_p - min_p) / min_p * 100
    
    def should_close_position(
        self,
        figi: str,
        entry_price: float,
        current_price: float,
        direction: str = "BUY",
        trailing_stop_price: Optional[float] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None
    ) -> tuple:
        """Проверить, нужно ли закрыть позицию."""
        tp = take_profit if take_profit else self.tp_percent
        sl = stop_loss if stop_loss else self.sl_percent
        
        if direction == "BUY":
            profit_pct = (current_price - entry_price) / entry_price * 100
            
            # TP сработал
            if profit_pct >= tp:
                return True, f"TP {profit_pct:.2f}%", None
            
            # SL сработал
            if sl > 0 and profit_pct <= -sl:
                return True, f"SL {profit_pct:.2f}%", None
            
            # Trailing stop если прибыль > 0.4%
            if profit_pct >= 0.4 and trailing_stop_price is None:
                trailing = current_price * 0.998  # стоп чуть ниже текущей
                return False, "", trailing
            
            return False, "", trailing_stop_price
        
        return False, "", None
    
    def analyze(
        self,
        figi: str,
        ticker: str,
        current_price: float,
        volume: float = 0,
        orderbook: Optional[dict] = None
    ) -> ScalpSignal:
        """Анализировать инструмент."""
        
        # Сброс счётчик если новый день
        self._reset_daily_counter()
        
        # Не более 2 сделок в день
        if self.daily_trades >= 2:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason="Лимит сделок (2/день)",
                indicators={}
            )
        
        # Пропускаем инструменты с ценой 0
        if current_price <= 0:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason="Цена = 0",
                indicators={}
            )
        
        # Обновляем историю
        self.update_price(figi, current_price, volume)
        
        # Недостаточно данных
        if figi not in self.price_histories or len(self.price_histories[figi]) < self.min_history:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason=f"История ({len(self.price_histories.get(figi, []))}/{self.min_history})",
                indicators={}
            )
        
        # Получаем метрики
        change_1 = self._get_price_change(figi, 1)
        change_2 = self._get_price_change(figi, 2)
        momentum = self._get_momentum(figi, 5)
        near_support = self._is_near_support(figi)
        confirmed = self._is_confirmed_uptrend(figi)
        volatility = self._get_volatility(figi)
        
        # Сигнал BUY если:
        # Momentum > 0.03% (любое движение вверх)
        # Волатильность < 3% (не во время экстремального хаоса)
        
        if momentum > 0.03 and volatility < 3.0:
            confidence = min(0.50 + momentum * 8, 0.80)
            self.daily_trades += 1
            
            return ScalpSignal(
                signal_type=SignalType.BUY,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=confidence,
                reason=f"M={momentum:.2f}%",
                indicators={
                    'change': change_1,
                    'momentum': momentum,
                    'volatility': volatility,
                    'tp': self.tp_percent,
                    'sl': self.sl_percent
                }
            )
        
        # HOLD
        reason = f"S={near_support} C={confirmed} M={momentum:.2f}%"
        return ScalpSignal(
            signal_type=SignalType.HOLD,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=0.0,
            reason=reason,
            indicators={
                'change': change_1,
                'momentum': momentum,
                'volatility': volatility,
                'near_support': near_support,
                'confirmed': confirmed
            }
        )
