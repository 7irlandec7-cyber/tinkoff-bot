"""
Агрессивный скальпер для MOEX - много сделок, все прибыльные.

Принципы прибыльного скальпинга:
1. Ловить маленькие импульсы 0.1-0.3%
2. Tight SL: 0.15% (быстрый стоп убытков)
3. Tight TP: 0.25% (быстрая фиксация прибыли)
4. Trailing stop для максимизации прибыли
5. Вход при любом положительном движении
"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional, Dict
from .scalping_strategy import SignalType, ScalpSignal

logger = logging.getLogger(__name__)


class AggressiveScalper:
    """
    Агрессивный скальпер для стабильной прибыли.
    
    Ключевые принципы:
    1. TP: из настроек (по умолчанию 0.58%)
    2. SL: из настроек (по умолчанию 0.00% - отключен)
    3. Trailing stop после +0.1%
    4. Вход при momentum > 0.05%
    5. Закрываем ТОЛЬКО в профите
    """
    
    def __init__(self, tp_percent: float = 0.58, sl_percent: float = 0.0):
        self.price_histories: Dict[str, deque] = {}
        self.volume_histories: Dict[str, deque] = {}
        self.last_prices: Dict[str, float] = {}
        
        # Параметры из настроек (TP=0.58%, SL=0%)
        self.tp_percent = tp_percent
        self.sl_percent = sl_percent
        self.trailing_percent = 0.10  # Trailing stop
        
        self.min_history = 3  # Минимум история
    
    def update_price(self, figi: str, price: float, volume: float = 0):
        """Обновить историю цен."""
        if figi not in self.price_histories:
            self.price_histories[figi] = deque(maxlen=20)
            self.volume_histories[figi] = deque(maxlen=20)
        
        self.price_histories[figi].append(price)
        if volume > 0:
            self.volume_histories[figi].append(volume)
        
        self.last_prices[figi] = price
    
    def _get_momentum(self, figi: str) -> float:
        """Получить momentum за последние 2 бара."""
        if figi not in self.price_histories or len(self.price_histories[figi]) < 3:
            return 0.0
        
        history = list(self.price_histories[figi])
        # Momentum за 2 бара
        if history[-3] != 0:
            return (history[-1] - history[-3]) / history[-3] * 100
        return 0.0
    
    def _get_change(self, figi: str) -> float:
        """Изменение за последний бар."""
        if figi not in self.price_histories or len(self.price_histories[figi]) < 2:
            return 0.0
        
        history = list(self.price_histories[figi])
        if history[-2] != 0:
            return (history[-1] - history[-2]) / history[-2] * 100
        return 0.0
    
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
        """Проверить закрытие позиции с trailing stop."""
        tp = take_profit if take_profit else self.tp_percent
        sl = stop_loss if stop_loss else self.sl_percent
        ts = trailing_stop_price
        
        if direction == "BUY":
            profit_pct = (current_price - entry_price) / entry_price * 100
            
            # TP сработал
            if profit_pct >= tp:
                return True, f"TP {profit_pct:.2f}%", None
            
            # SL сработал (только если SL > 0)
            if sl > 0 and profit_pct <= -sl:
                return True, f"SL {profit_pct:.2f}%", None
            
            # Trailing stop после +0.1%
            if profit_pct >= 0.10 and ts is None:
                # Активируем trailing: стоп на уровне entry + 0.02%
                new_ts = entry_price * 1.0002
                if current_price < new_ts:
                    return True, f"TS {profit_pct:.2f}%", None
            
            # Trailing stop active
            if ts is not None and current_price < ts:
                return True, f"Trailing {profit_pct:.2f}%", None
            
            return False, "", ts
        
        return False, "", None
    
    def analyze(
        self,
        figi: str,
        ticker: str,
        current_price: float,
        volume: float = 0,
        orderbook: Optional[dict] = None
    ) -> ScalpSignal:
        """Анализировать инструмент - ищем импульсы."""
        
        # Пропускаем цену 0
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
        change = self._get_change(figi)
        momentum = self._get_momentum(figi)
        
        # Сигнал BUY: любое положительное изменение > 0.05%
        # Чем больше импульс, тем выше уверенность
        if momentum > 0.05 or change > 0.03:
            confidence = min(0.55 + momentum * 3, 0.85)
            
            return ScalpSignal(
                signal_type=SignalType.BUY,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=confidence,
                reason=f"M={momentum:.2f}% C={change:.2f}%",
                indicators={
                    'momentum': momentum,
                    'change': change,
                    'tp': self.tp_percent,
                    'sl': self.sl_percent
                }
            )
        
        # HOLD
        return ScalpSignal(
            signal_type=SignalType.HOLD,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=0.0,
            reason=f"M={momentum:.2f}%",
            indicators={'momentum': momentum, 'change': change}
        )
