"""
Надёжная стратегия для MOEX скальпинга.
Основные принципы:
1. Только BUY (не шортить)
2. Входить от поддержки (цена near low)
3. Использовать объём как подтверждение
4. Trailing stop для защиты прибыли
5. Индекс как фильтр тренда
"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional, Dict
from .scalping_strategy import SignalType, ScalpSignal

logger = logging.getLogger(__name__)


@dataclass
class SupportLevel:
    """Уровень поддержки."""
    price: float
    strength: int  # количество касаний


class ReliableScalpingStrategy:
    """
    Надёжная стратегия скальпинга.
    
    Входы:
    - Цена near поддержки (lowest 20% диапазона)
    - Объём выше среднего (>1.5x)
    - Индекс IMOEX не падает
    
    Выходы:
    - Trailing stop
    - Фиксированный TP (0.3-0.5%)
    """
    
    def __init__(self):
        self.price_histories: Dict[str, deque] = {}
        self.volume_histories: Dict[str, deque] = {}
        self.index_history: deque = deque(maxlen=50)
        
        # Параметры
        self.min_history = 5  # минимум 5 баров для анализа
        self.volume_multiplier = 1.2  # объём должен быть > 1.2x среднего
        self.range_percent = 0.25  # поддержка = lowest 25% диапазона
        
        # Trailing stop
        self.trailing_activated_at = 0.2  # активировать при +0.2%
        self.trailing_distance = 0.15  # стоп на 0.15% ниже high
        
    def update_price(self, figi: str, price: float):
        """Обновить историю цен."""
        if figi not in self.price_histories:
            self.price_histories[figi] = deque(maxlen=100)
        self.price_histories[figi].append(price)
    
    def update_volume(self, figi: str, volume: float):
        """Обновить историю объёмов."""
        if figi not in self.volume_histories:
            self.volume_histories[figi] = deque(maxlen=50)
        self.volume_histories[figi].append(volume)
    
    def _is_near_support(self, figi: str, current_price: float) -> bool:
        """Проверить, находится ли цена near поддержки."""
        if figi not in self.price_histories or len(self.price_histories[figi]) < 10:
            return False
        
        history = list(self.price_histories[figi])
        min_price = min(history)
        max_price = max(history)
        
        if max_price == min_price:
            return False
        
        # Поддержка = lowest 20% диапазона
        support_level = min_price + (max_price - min_price) * self.range_percent
        
        # Цена должна быть не далее 0.5% от поддержки
        return current_price <= support_level * 1.005
    
    def _check_volume_surge(self, figi: str) -> bool:
        """Проверить всплеск объёма."""
        if figi not in self.volume_histories or len(self.volume_histories[figi]) < 5:
            return True  # Пропускаем если нет данных
        
        volumes = list(self.volume_histories[figi])
        avg_volume = sum(volumes[-10:]) / min(10, len(volumes))
        
        if avg_volume == 0:
            return False
        
        current_volume = volumes[-1] if volumes else 0
        return current_volume >= avg_volume * self.volume_multiplier
    
    def _get_momentum(self, figi: str) -> float:
        """Получить momentum (изменение за последние N баров)."""
        if figi not in self.price_histories or len(self.price_histories[figi]) < 5:
            return 0.0
        
        history = list(self.price_histories[figi])
        if len(history) < 3:
            return 0.0
        
        # Momentum = % изменения от earliest к latest
        if len(history) >= 5 and history[-5] != 0:
            change = (history[-1] - history[-5]) / history[-5] * 100
        else:
            change = 0.0
        return change
    
    def _is_index_bullish(self) -> bool:
        """Проверить, растёт ли индекс."""
        if len(self.index_history) < 5:
            return True  # Пропускаем если нет данных
        
        history = list(self.index_history)
        return history[-1] >= history[-3]  # Текущий >= 2 бара назад
    
    def should_close_long(
        self,
        figi: str,
        entry_price: float,
        current_price: float,
        trailing_stop_price: Optional[float] = None
    ) -> tuple:
        """
        Проверить, нужно ли закрыть длинную позицию.
        
        Returns: (should_close, reason, new_trailing_stop)
        """
        if trailing_stop_price is None:
            trailing_stop_price = entry_price * (1 - 0.003)  # Начальный стоп -0.3%
        
        profit_pct = (current_price - entry_price) / entry_price * 100
        
        # Trailing stop logic
        if profit_pct >= self.trailing_activated_at:
            # Поднимаем стоп
            new_trailing = current_price * (1 - self.trailing_distance / 100)
            if new_trailing > trailing_stop_price:
                trailing_stop_price = new_trailing
        
        # Проверяем срабатывание стопа
        if current_price <= trailing_stop_price:
            return True, f"Trailing Stop: {profit_pct:.2f}%", trailing_stop_price
        
        # TP reached
        if profit_pct >= 0.5:  # TP = +0.5%
            return True, f"TP: {profit_pct:.2f}%", trailing_stop_price
        
        return False, "", trailing_stop_price
    
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
        if direction == "BUY":
            return self.should_close_long(figi, entry_price, current_price, trailing_stop_price)
        else:
            return self.should_close_long(figi, entry_price, current_price, trailing_stop_price)
    
    def analyze(
        self,
        figi: str,
        ticker: str,
        current_price: float,
        volume: float = 0,
        orderbook: Optional[dict] = None
    ) -> ScalpSignal:
        """Анализировать инструмент и вернуть сигнал."""
        
        # Обновляем историю
        self.update_price(figi, current_price)
        if volume > 0:
            self.update_volume(figi, volume)
        
        # Недостаточно данных
        if figi not in self.price_histories or len(self.price_histories[figi]) < self.min_history:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason=f"Сбор истории ({len(self.price_histories.get(figi, []))}/{self.min_history})",
                indicators={}
            )
        
        # Получаем метрики
        momentum = self._get_momentum(figi)
        near_support = self._is_near_support(figi, current_price)
        volume_ok = self._check_volume_surge(figi)
        index_ok = self._is_index_bullish()
        
        # Сигнал BUY если:
        # 1. Цена near поддержки
        # 2. Momentum положительный или нейтральный
        # 3. Индекс не падает
        if near_support and momentum > -0.1 and index_ok:
            # Рассчитываем уверенность
            confidence = 0.5
            
            if volume_ok:
                confidence += 0.2
            
            if momentum > 0.05:
                confidence += 0.2
            
            if near_support and volume_ok:
                confidence += 0.1
            
            confidence = min(confidence, 0.9)
            
            reason = f"Support+Volume M={momentum:.2f}"
            if volume_ok:
                reason += " Vol=OK"
            
            return ScalpSignal(
                signal_type=SignalType.BUY,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=confidence,
                reason=reason,
                indicators={
                    'momentum': momentum,
                    'near_support': near_support,
                    'volume_ok': volume_ok
                }
            )
        
        # HOLD сигнал
        return ScalpSignal(
            signal_type=SignalType.HOLD,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=0.0,
            reason=f"M={momentum:.2f} S={near_support} V={volume_ok}",
            indicators={}
        )
