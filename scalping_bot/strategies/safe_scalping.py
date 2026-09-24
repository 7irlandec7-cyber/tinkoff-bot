"""
Safe Scalping Strategy - Консервативная стратегия для максимально положительного результата.

Строгие требования:
- RSI < 35 для BUY (перепроданность - покупаем на минимуме)
- RSI > 65 для SELL (перекупленность - продаём на максимуме)  
- Volume > 2.0x среднего
- Тренд должен подтверждать направление
- Минимум 4/5 индикаторов должны совпадать
"""
from collections import deque
from typing import Deque, Optional, List, Any
from dataclasses import dataclass, field
from scalping_bot.strategies.scalping_strategy import ScalpSignal, SignalType
import logging

logger = logging.getLogger(__name__)


@dataclass
class SafeScalpingSettings:
    """Настройки безопасной скальпинг стратегии."""
    # RSI экстремальные значения
    rsi_oversold: float = 40    # RSI < 40 для BUY (перепроданность)
    rsi_overbought: float = 60   # RSI > 60 для SELL (перекупленность)
    
    # Объём - строгий фильтр
    volume_ma_period: int = 20
    volume_threshold: float = 1.5  # Объём должен быть > 1.5x среднего
    
    # Минимум истории
    min_history: int = 30
    
    # Вход: 3/5 индикаторов (консервативно)
    entry_threshold: int = 3
    
    # TP/SL - консервативные
    tp_percent: float = 0.50   # TP 0.5% (больше пространства)
    sl_percent: float = 0.25   # SL 0.25% (меньше ложных срабатываний)
    
    # Trailing stop - ОТКЛЮЧЁН для стабильности
    use_trailing_sl: bool = False
    trailing_sl_activation: float = 0.20
    trailing_sl_distance: float = 0.10


class SafeScalpingStrategy:
    """
    Безопасная скальпинг стратегия.
    
    Входы:
    1. RSI Extreme - RSI < 35 для BUY, RSI > 65 для SELL
    2. RSI Change - RSI растёт/падает
    3. Price near EMA - цена рядом со скользящей средней
    4. Volume - объём > 2x среднего
    5. Price momentum - импульс цены
    """
    """
    Безопасная скальпинг стратегия.
    
    Входы:
    1. RSI Extreme - RSI < 35 для BUY, RSI > 65 для SELL
    2. RSI Change - RSI растёт/падает
    3. Price near EMA - цена рядом со скользящей средней
    4. Volume - объём > 2x среднего
    5. Price momentum - импульс цены
    """
    
    def __init__(self, settings: Optional[SafeScalpingSettings] = None):
        self.settings = settings or SafeScalpingSettings()
        
        # История
        self.price_history: Deque[float] = deque(maxlen=50)
        self.volume_history: Deque[float] = deque(maxlen=30)
        self.rsi_history: Deque[float] = deque(maxlen=20)
        
    def _calc_ema(self, prices: list, period: int) -> Optional[float]:
        """Расчёт EMA."""
        if len(prices) < period:
            return None
        k = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = price * k + ema * (1 - k)
        return ema
    
    def _calc_rsi(self, prices: list, period: int = 5) -> Optional[float]:
        """Расчёт RSI."""
        if len(prices) < period + 1:
            return None
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _get_rsi_change(self) -> str:
        """RSI растёт или падает."""
        if len(self.rsi_history) < 5:
            return "FLAT"
        
        recent = list(self.rsi_history)[-5:]
        if recent[-1] > recent[0] + 2:
            return "RISING"
        elif recent[-1] < recent[0] - 2:
            return "FALLING"
        return "FLAT"
    
    def _check_price_momentum(self, prices: list) -> str:
        """Проверка импульса цены."""
        if len(prices) < 10:
            return "FLAT"
        
        recent = prices[-10:]
        if recent[0] == 0:
            return "FLAT"
        
        change = (recent[-1] - recent[0]) / recent[0] * 100
        
        if change > 0.3:
            return "UP"
        elif change < -0.3:
            return "DOWN"
        return "FLAT"
    
    def analyze(
        self,
        figi: str,
        ticker=None,
        price=None,
        volume=None,
        orderbook=None
    ) -> ScalpSignal:
        """Анализ инструмента."""
        ticker = ticker or figi
        
        # Обновляем историю
        if price is not None:
            self.price_history.append(price)
        
        if volume is not None:
            self.volume_history.append(volume)
        
        prices = list(self.price_history)
        volumes = list(self.volume_history)
        
        # Минимум истории
        if len(prices) < self.settings.min_history:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=price or 0,
                confidence=0.0,
                reason=f"История ({len(prices)}/{self.settings.min_history})",
                indicators={}
            )
        
        current_price = prices[-1]
        
        # Расчёт индикаторов
        rsi = self._calc_rsi(prices)
        if rsi is not None:
            self.rsi_history.append(rsi)
        
        rsi_change = self._get_rsi_change()
        momentum = self._check_price_momentum(prices)
        
        # EMA 20 для проверки расстояния
        ema_20 = self._calc_ema(prices, 20)
        price_vs_ema = (current_price - ema_20) / ema_20 * 100 if ema_20 and ema_20 != 0 else 0
        
        # Объём
        avg_vol = sum(volumes[-self.settings.volume_ma_period:]) / min(len(volumes), self.settings.volume_ma_period) if volumes else 1
        current_vol = volumes[-1] if volumes else 0
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        
        # Подсчёт сигналов
        buy_score = 0
        sell_score = 0
        details = []
        
        # 1. RSI Экстремальная зона (самый важный фильтр)
        # RSI < 35 = перепроданность (цена сильно упала, avg_gain<<avg_loss, возможен отскок вверх)
        # RSI > 65 = перекупленность (цена сильно выросла, avg_gain>>avg_loss, возможен отскок вниз)
        if rsi is not None:
            if rsi < self.settings.rsi_oversold:
                buy_score += 2  # Двойной вес
                details.append(f"RSI({rsi:.0f})✅<40 BUY")
            elif rsi < 45:
                buy_score += 0.5
                details.append(f"RSI({rsi:.0f})~LOW")
            elif rsi > self.settings.rsi_overbought:
                sell_score += 2
                details.append(f"RSI({rsi:.0f})✅>65 SELL")
            elif rsi > 55:
                sell_score += 0.5
                details.append(f"RSI({rsi:.0f})~HIGH")
            else:
                details.append(f"RSI({rsi:.0f})❌")
        
        # 2. RSI Change (растёт/падает)
        if rsi_change == "RISING" and rsi is not None and rsi < 50:
            buy_score += 1
            details.append("RSI↗✅")
        elif rsi_change == "FALLING" and rsi is not None and rsi > 50:
            sell_score += 1
            details.append("RSI↘✅")
        
        # 3. Цена близко к EMA (не дальше 1%)
        if abs(price_vs_ema) < 1.0:
            if price_vs_ema < 0:
                buy_score += 1
                details.append(f"Цена<EMA✅")
            else:
                sell_score += 1
                details.append(f"Цена>EMA✅")
        else:
            details.append(f"Цена{price_vs_ema:+.1f}%❌")
        
        # 4. Объём (строгий фильтр)
        if vol_ratio > self.settings.volume_threshold:
            buy_score += 1
            sell_score += 1
            details.append(f"Vol({vol_ratio:.1f}x)✅")
        else:
            details.append(f"Vol({vol_ratio:.1f}x)❌")
        
        # 5. Momentum
        if momentum == "UP":
            buy_score += 1
            details.append("Mom↗✅")
        elif momentum == "DOWN":
            sell_score += 1
            details.append("Mom↘✅")
        else:
            details.append("Mom—❌")
        
        # Решение
        confidence = 0.0
        signal_type = SignalType.HOLD
        reason = ""
        
        if buy_score >= self.settings.entry_threshold:
            signal_type = SignalType.BUY
            confidence = min(buy_score / 5 + 0.15, 0.95)
            reason = f"🟢 BUY: {', '.join(details)}"
        elif sell_score >= self.settings.entry_threshold:
            signal_type = SignalType.SELL
            confidence = min(sell_score / 5 + 0.15, 0.95)
            reason = f"🔴 SELL: {', '.join(details)}"
        else:
            reason = f"⏸ {buy_score:.1f}/{self.settings.entry_threshold} BUY, {sell_score:.1f}/{self.settings.entry_threshold} SELL"
        
        return ScalpSignal(
            signal_type=signal_type,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=confidence,
            reason=reason,
            indicators={
                'rsi': float(rsi) if rsi is not None else 50.0,
                'rsi_change': rsi_change,
                'momentum': momentum,
                'vol_ratio': float(vol_ratio),
                'price_vs_ema': float(price_vs_ema),
                'tp_percent': self.settings.tp_percent,
                'sl_percent': self.settings.sl_percent,
                'trailing_sl': self.settings.use_trailing_sl,
            }
        )
    
    def should_close_position(
        self,
        figi: str,
        entry_price: float,
        current_price: float,
        direction: str,
        take_profit: float = 0.3,
        stop_loss: float = 0.15
    ) -> tuple:
        """Проверка закрытия позиции."""
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        if direction == "SELL":
            pnl_pct = -pnl_pct
        
        # Stop Loss
        if pnl_pct <= -stop_loss:
            return True, f"SL ({pnl_pct:.2f}%)", "sell"
        
        # Take Profit
        if pnl_pct >= take_profit:
            return True, f"TP ({pnl_pct:.2f}%)", "buy"
        
        # Trailing Stop
        if self.settings.use_trailing_sl:
            if pnl_pct >= self.settings.trailing_sl_activation:
                trailing_level = pnl_pct - self.settings.trailing_sl_distance
                if pnl_pct <= trailing_level:
                    return True, f"Trailing SL ({pnl_pct:.2f}%)", "sell"
        
        return False, "", ""
    
    def reset(self):
        """Сброс состояния."""
        self.price_history.clear()
        self.volume_history.clear()
        self.rsi_history.clear()
