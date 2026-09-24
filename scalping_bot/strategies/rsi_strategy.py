"""
RSI + EMA Scalping Strategy - Проверенная временем стратегия
"""
import logging
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime
from collections import deque
import statistics

from .scalping_strategy import SignalType, ScalpSignal

logger = logging.getLogger(__name__)


class RSIEMAStrategy:
    """
    RSI + EMA стратегия для скальпинга.
    
    Комбинирует:
    - RSI (Relative Strength Index) для определения перекупленности/перепроданности
    - EMA (Exponential Moving Average) для определения тренда
    - Объём для подтверждения сигналов
    
    RSI параметры:
    - period: период RSI (14 - классика)
    - oversold: уровень перепроданности (30)
    - overbought: уровень перекупленности (70)
    
    EMA параметры:
    - fast_period: быстрая EMA (9)
    - slow_period: медленная EMA (21)
    
    Сигналы:
    - BUY: RSI < 30 (перепроданность) + цена выше быстрой EMA + объём > среднего
    - SELL: RSI > 70 (перекупленность) + цена ниже быстрой EMA + объём > среднего
    """
    
    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        ema_fast: int = 9,
        ema_slow: int = 21,
        volume_boost: float = 1.5,  # Минимальное превышение объёма
    ):
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.volume_boost = volume_boost
        
        # История цен и объёмов для всех инструментов
        self.price_history: Dict[str, deque] = {}
        self.volume_history: Dict[str, deque] = {}
        
        logger.info(
            f"📊 RSI+EMA стратегия: RSI({rsi_period}), EMA({ema_fast}/{ema_slow}), "
            f"OS={rsi_oversold}, OB={rsi_overbought}"
        )
    
    def _calculate_ema(self, values: List[float], period: int) -> Optional[float]:
        """Расчёт EMA."""
        if len(values) < period:
            return None
        
        # Используем SMA как начальную точку
        sma = sum(values[:period]) / period
        multiplier = 2 / (period + 1)
        
        ema = sma
        for value in values[period:]:
            ema = (value - ema) * multiplier + ema
        
        return ema
    
    def _calculate_rsi(self, changes: deque) -> Optional[float]:
        """Расчёт RSI."""
        if len(changes) < self.rsi_period + 1:
            return None
        
        gains = []
        losses = []
        for change in list(changes)[-self.rsi_period:]:
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        
        if avg_loss == 0:
            return 100  # Все изменения положительные
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _get_history(self, figi: str) -> deque:
        """Получить историю цен."""
        if figi not in self.price_history:
            self.price_history[figi] = deque(maxlen=50)
        return self.price_history[figi]
    
    def _get_volume_history(self, figi: str) -> deque:
        """Получить историю объёмов."""
        if figi not in self.volume_history:
            self.volume_history[figi] = deque(maxlen=20)
        return self.volume_history[figi]
    
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
            figi: FIGI код
            ticker: Тикер
            current_price: Текущая цена
            volume: Объём (опционально)
        
        Returns:
            ScalpSignal
        """
        # Добавляем цену в историю
        history = self._get_history(figi)
        history.append(current_price)
        
        # Добавляем объём
        if volume > 0:
            vol_history = self._get_volume_history(figi)
            vol_history.append(volume)
        
        # Минимум данных для RSI + EMA
        min_required = max(self.rsi_period, self.ema_slow) + 2
        if len(history) < min_required:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason=f"Недостаточно данных ({len(history)}/{min_required})",
                indicators={}
            )
        
        # Рассчитываем изменения для RSI
        changes = deque(maxlen=self.rsi_period + 1)
        prices = list(history)
        for i in range(1, len(prices)):
            change = (prices[i] - prices[i-1]) / prices[i-1] * 100
            changes.append(change)
        
        # RSI
        rsi = self._calculate_rsi(changes)
        
        # EMA
        ema_fast = self._calculate_ema(prices, self.ema_fast)
        ema_slow = self._calculate_ema(prices, self.ema_slow)
        
        # Средний объём
        avg_volume = 0
        if volume > 0 and figi in self.volume_history:
            avg_volume = statistics.mean(self.volume_history[figi]) if self.volume_history[figi] else 0
        
        indicators = {
            "rsi": rsi or 50,
            "ema_fast": ema_fast or current_price,
            "ema_slow": ema_slow or current_price,
            "volume": volume,
            "avg_volume": avg_volume,
            "above_fast": current_price > ema_fast if ema_fast else False,
            "above_slow": current_price > ema_slow if ema_slow else False,
        }
        
        # Определяем сигнал
        signal_type = SignalType.HOLD
        confidence = 0.0
        reason = ""
        
        # BUY: RSI перепродан + цена выше EMA + объём подтверждает
        if rsi and rsi < self.rsi_oversold:
            bullish = current_price > (ema_fast or 0)
            volume_confirm = volume >= avg_volume * self.volume_boost if avg_volume > 0 else True
            
            if bullish and volume_confirm:
                # Сила сигнала зависит от RSI
                rsi_strength = (self.rsi_oversold - rsi) / self.rsi_oversold
                ema_strength = (current_price - ema_fast) / ema_fast * 100 if ema_fast else 0
                
                confidence = min(0.5 + rsi_strength * 0.4, 0.95)
                
                signal_type = SignalType.BUY
                reason = f"RSI={rsi:.1f} < {self.rsi_oversold}, EMA confirmation"
                
                indicators["signal_reason"] = "oversold_rsi"
                indicators["rsi_strength"] = rsi_strength
        
        # SELL: RSI перекуплен + цена ниже EMA + объём подтверждает
        elif rsi and rsi > self.rsi_overbought:
            bearish = current_price < (ema_fast or float('inf'))
            volume_confirm = volume >= avg_volume * self.volume_boost if avg_volume > 0 else True
            
            if bearish and volume_confirm:
                rsi_strength = (rsi - self.rsi_overbought) / (100 - self.rsi_overbought)
                
                confidence = min(0.5 + rsi_strength * 0.4, 0.95)
                
                signal_type = SignalType.SELL
                reason = f"RSI={rsi:.1f} > {self.rsi_overbought}, EMA confirmation"
                
                indicators["signal_reason"] = "overbought_rsi"
                indicators["rsi_strength"] = rsi_strength
        
        # Нет сигнала
        if signal_type == SignalType.HOLD:
            ema_diff = ((ema_fast - ema_slow) / ema_slow * 100) if ema_slow and ema_fast else 0
            reason = f"RSI={rsi:.1f if rsi else 'N/A'}, EMA diff={ema_diff:.1f}%"
        
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
        if figi in self.price_history:
            del self.price_history[figi]
        if figi in self.volume_history:
            del self.volume_history[figi]
    
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


def get_rsi_strategy() -> RSIEMAStrategy:
    """Получить экземпляр RSI+EMA стратегии."""
    return RSIEMAStrategy(
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
        ema_fast=9,
        ema_slow=21,
        volume_boost=1.5,
    )
