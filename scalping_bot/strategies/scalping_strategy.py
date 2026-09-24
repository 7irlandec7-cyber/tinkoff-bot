"""
Scalping Strategy Module - Simple Momentum Strategy
"""
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from collections import deque
import statistics

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Тип торгового сигнала."""
    BUY = "BUY"
    SELL = "SELL"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    HOLD = "HOLD"


@dataclass
class ScalpSignal:
    """Сигнал для скальпинга."""
    signal_type: SignalType
    figi: str
    ticker: str
    price: float
    confidence: float  # 0.0 - 1.0
    reason: str
    indicators: Dict[str, Any]  # Changed from Dict[str, float] to allow mixed types
    
    def __str__(self):
        emoji = "🟢" if self.signal_type == SignalType.BUY else "🔴" if self.signal_type == SignalType.SELL else "⚪"
        return f"{emoji} {self.signal_type.value} {self.ticker} @ {self.price:.2f} ({self.confidence:.0%})"


class PriceHistory:
    """Хранит историю цен для инструмента."""
    
    def __init__(self, max_size: int = 20):
        self.prices: deque = deque(maxlen=max_size)
        self.timestamps: deque = deque(maxlen=max_size)
        self.changes: deque = deque(maxlen=max_size)
    
    def add(self, price: float, timestamp: Optional[datetime] = None):
        """Добавить новую цену."""
        if price <= 0:
            return  # Защита от некорректных цен
        
        if self.prices and self.prices[-1] > 0:
            change = (price - self.prices[-1]) / self.prices[-1] * 100
            self.changes.append(change)
        
        self.prices.append(price)
        self.timestamps.append(timestamp or datetime.now())
    
    def get_momentum(self) -> float:
        """Получить моментум (среднее изменение в %)."""
        if len(self.changes) < 3:
            return 0.0
        return statistics.mean(list(self.changes)[-5:])
    
    def get_volatility(self) -> float:
        """Получить волатильность (std изменений в %)."""
        if len(self.changes) < 3:
            return 0.0
        return statistics.stdev(list(self.changes)) if len(self.changes) > 1 else 0.0
    
    def get_trend(self) -> float:
        """Получить тренд (изменение за период)."""
        if len(self.prices) < 5:
            return 0.0
        first = list(self.prices)[0]
        last = list(self.prices)[-1]
        return (last - first) / first * 100 if first > 0 else 0.0


class SimpleMomentumStrategy:
    """
    Простая моментум-стратегия для скальпинга.
    
    Генерирует сигналы на основе:
    - Изменение цены за последние N минут
    - Волатильность
    - Объём (если доступен)
    
    Параметры:
    - price_change_threshold: % изменения для сигнала (по умолчанию 0.3%)
    - momentum_threshold: минимальный моментум (по умолчанию 0.1%)
    - volatility_max: максимальная волатильность для входа (5%)
    """
    
    def __init__(
        self,
        price_change_threshold: float = 0.3,
        momentum_threshold: float = 0.1,
        volatility_max: float = 5.0,
        min_history: int = 5
    ):
        self.price_change_threshold = price_change_threshold
        self.momentum_threshold = momentum_threshold
        self.volatility_max = volatility_max
        self.min_history = min_history
        
        # История цен для всех инструментов
        self.price_history: Dict[str, PriceHistory] = {}
        
        logger.info(f"📊 Стратегия инициализирована: change={price_change_threshold}%, momentum={momentum_threshold}%")
    
    def _get_history(self, figi: str) -> PriceHistory:
        """Получить или создать историю цен."""
        if figi not in self.price_history:
            self.price_history[figi] = PriceHistory()
        return self.price_history[figi]
    
    def analyze(
        self,
        figi: str,
        ticker: str,
        current_price: float,
        volume: float = 0,
        orderbook: Optional[Dict] = None,
    ) -> ScalpSignal:
        """
        Анализировать инструмент и вернуть сигнал.
        
        Args:
            figi: FIGI код инструмента
            ticker: Тикер
            current_price: Текущая цена
            volume: Объём (опционально)
        
        Returns:
            ScalpSignal с типом сигнала
        """
        history = self._get_history(figi)
        history.add(current_price)
        
        # Получаем метрики
        momentum = history.get_momentum()
        volatility = history.get_volatility()
        trend = history.get_trend()
        
        indicators = {
            "momentum": momentum,
            "volatility": volatility,
            "trend": trend,
            "history_size": len(history.prices)
        }
        
        # Недостаточно данных
        if len(history.prices) < self.min_history:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason="Недостаточно данных для анализа",
                indicators=indicators
            )
        
        # Проверка волатильности
        if volatility > self.volatility_max:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.3,
                reason=f"Высокая волатильность: {volatility:.1f}%",
                indicators=indicators
            )
        
        # Сигнал на покупку
        if momentum > self.momentum_threshold and trend > self.price_change_threshold:
            confidence = min(abs(momentum) / 1.0, 0.9) * 0.8  # 0-72%
            if volatility > 0.5:
                confidence *= 1.2  # Буст при умеренной волатильности
            
            return ScalpSignal(
                signal_type=SignalType.BUY,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=min(confidence, 0.9),
                reason=f"Позитивный моментум: {momentum:.2f}%, тренд: {trend:.2f}%",
                indicators=indicators
            )
        
        # Сигнал на продажу
        if momentum < -self.momentum_threshold and trend < -self.price_change_threshold:
            confidence = min(abs(momentum) / 1.0, 0.9) * 0.8  # 0-72%
            if volatility > 0.5:
                confidence *= 1.2  # Буст при умеренной волатильности
            
            return ScalpSignal(
                signal_type=SignalType.SELL,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=min(confidence, 0.9),
                reason=f"Негативный моментум: {momentum:.2f}%, тренд: {trend:.2f}%",
                indicators=indicators
            )
        
        # Нет сигнала
        return ScalpSignal(
            signal_type=SignalType.HOLD,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=0.1,
            reason=f"Нет сигнала (momentum={momentum:.2f}%, trend={trend:.2f}%)",
            indicators=indicators
        )
    
    def reset(self, figi: str):
        """Сбросить историю для инструмента."""
        if figi in self.price_history:
            del self.price_history[figi]
    
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
            # Для шорта: закрываем если цена выросла (убыток)
            if pnl_percent > stop_loss:
                return True, f"Стоп-лосс: {pnl_percent:.2f}%"
            if pnl_percent < -take_profit:
                return True, f"Тейк-профит: {pnl_percent:.2f}%"
        else:
            # Для лонга: закрываем если цена упала (убыток)
            if pnl_percent < -stop_loss:
                return True, f"Стоп-лосс: {pnl_percent:.2f}%"
            if pnl_percent > take_profit:
                return True, f"Тейк-профит: {pnl_percent:.2f}%"
        
        return False, ""


# Алиас для обратной совместимости
ScalpingStrategy = SimpleMomentumStrategy


def get_strategy() -> SimpleMomentumStrategy:
    """Получить экземпляр стратегии."""
    return SimpleMomentumStrategy(
        price_change_threshold=0.05,  # 0.05% изменения цены (очень чувствительный)
        momentum_threshold=0.02,       # 0.02% минимальный моментум
        volatility_max=10.0,           # макс 10% волатильность
        min_history=2                  # минимум 2 точки данных
    )
