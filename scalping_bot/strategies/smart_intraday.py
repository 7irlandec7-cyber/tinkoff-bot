"""
Smart Intraday Strategy - Использует EMA и объём вместо RSI/Stochastic
"""
from collections import deque
from typing import Deque, Optional, List, Any
from dataclasses import dataclass, field
from scalping_bot.strategies.scalping_strategy import ScalpSignal, SignalType


@dataclass
class SmartIntradaySettings:
    """Настройки умной интрадей стратегии."""
    # EMA периоды
    ema_fast: int = 8      # Быстрая EMA
    ema_slow: int = 21     # Медленная EMA
    ema_signal: int = 9     # Сигнальная EMA для MACD
    
    # RSI как фильтр
    rsi_period: int = 14
    rsi_filter_low: float = 40   # RSI выше 40 для BUY
    rsi_filter_high: float = 60   # RSI ниже 60 для SELL
    
    # Объём
    volume_ma_period: int = 20
    volume_threshold: float = 1.5  # Объём должен быть > 1.5x среднего
    
    # Минимум истории
    min_history: int = 25
    
    # Вход: 3/4 индикаторов
    entry_threshold: int = 3
    
    # TP/SL
    tp_percent: float = 0.50
    sl_percent: float = 0.30
    
    # Trailing stop
    use_trailing_sl: bool = True
    trailing_sl_activation: float = 0.30  # Активируется при 0.3% прибыли
    trailing_sl_distance: float = 0.15    # Стоп на 0.15% от максимума


class SmartIntradayStrategy:
    """
    Умная интрадей стратегия.
    
    Входы:
    1. EMA Cross - EMA 8 пересекает EMA 21
    2. MACD - MACD пересекает сигнальную линию
    3. RSI Filter - RSI в правильной зоне
    4. Volume - объём выше среднего
    """
    
    def __init__(self, settings: SmartIntradaySettings = None):
        self.settings = settings or SmartIntradaySettings()
        
        # История цен для индикаторов
        self.price_history: Deque[float] = deque(maxlen=50)
        self.volume_history: Deque[float] = deque(maxlen=30)
        
        # Кэш индикаторов
        self._ema_fast_cache: Deque[float] = deque(maxlen=50)
        self._ema_slow_cache: Deque[float] = deque(maxlen=50)
        self._macd_cache: Deque[float] = deque(maxlen=20)
        self._rsi_cache: Deque[float] = deque(maxlen=14)
        
        # Следящий стоп
        self.trailing_stop_high: float = 0
        self.trailing_stop_price: float = 0
        self.trailing_stop_active: bool = False
        
        print(f"📊 SmartIntraday Strategy:")
        print(f"   EMA: {self.settings.ema_fast}/{self.settings.ema_slow}")
        print(f"   RSI Filter: {self.settings.rsi_filter_low}/{self.settings.rsi_filter_high}")
        print(f"   Volume: >{self.settings.volume_threshold}x avg")
        print(f"   TP: {self.settings.tp_percent}% | SL: {self.settings.sl_percent}%")
    
    def _calc_ema(self, data: list, period: int) -> Optional[float]:
        """Расчёт EMA."""
        if len(data) < period:
            return None
        
        # Используем простую EMA
        multiplier = 2 / (period + 1)
        
        # Начальное значение = SMA
        ema = sum(data[:period]) / period
        
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def _calc_rsi(self, prices: list) -> Optional[float]:
        """Расчёт RSI."""
        if len(prices) < self.settings.rsi_period + 1:
            return None
        
        period = self.settings.rsi_period
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
    
    def _calc_macd(self, prices: list) -> tuple:
        """Расчёт MACD: (macd_line, signal_line, histogram)"""
        if len(prices) < 26:
            return None, None, None
        
        ema_12 = self._calc_ema(prices, 12)
        ema_26 = self._calc_ema(prices, 26)
        
        if ema_12 is None or ema_26 is None:
            return None, None, None
        
        macd_line = ema_12 - ema_26
        
        # Сигнальная линия = EMA от MACD
        macd_history = list(self._macd_cache)
        if len(macd_history) >= 9:
            signal_line = self._calc_ema(macd_history, 9)
        else:
            signal_line = macd_line
        
        histogram = macd_line - signal_line if signal_line else 0
        
        return macd_line, signal_line, histogram
    
    def _get_trend(self, prices: list) -> str:
        """Определение тренда по EMA."""
        if len(prices) < self.settings.ema_slow + 5:
            return "FLAT"
        
        ema_f = self._calc_ema(prices, self.settings.ema_fast)
        ema_s = self._calc_ema(prices, self.settings.ema_slow)
        
        if ema_f is None or ema_s is None:
            return "FLAT"
        
        # Тренд определяется по положению EMA относительно друг друга
        if ema_f > ema_s * 1.002:  # С запасом
            return "UP"
        elif ema_f < ema_s * 0.998:
            return "DOWN"
        else:
            return "FLAT"
    
    def _check_ema_cross(self, prices: list) -> tuple:
        """Проверка пересечения EMA."""
        if len(prices) < self.settings.ema_slow + 3:
            return False, "FLAT"
        
        # Текущие EMA
        ema_f_now = self._calc_ema(prices, self.settings.ema_fast)
        ema_s_now = self._calc_ema(prices, self.settings.ema_slow)
        
        # EMA 3 бара назад
        ema_f_prev = self._calc_ema(prices[:-1], self.settings.ema_fast)
        ema_s_prev = self._calc_ema(prices[:-1], self.settings.ema_slow)
        
        if None in (ema_f_now, ema_s_now, ema_f_prev, ema_s_prev):
            return False, "FLAT"
        
        # Бычье пересечение: EMA_fast была ниже EMA_slow, стала выше
        was_below = ema_f_prev < ema_s_prev if (ema_f_prev and ema_s_prev) else False
        is_above = ema_f_now > ema_s_now if (ema_f_now and ema_s_now) else False
        
        if was_below and is_above:
            return True, "BUY"
        
        # Медвежье пересечение
        was_above = ema_f_prev > ema_s_prev if (ema_f_prev and ema_s_prev) else False
        is_below = ema_f_now < ema_s_now if (ema_f_now and ema_s_now) else False
        
        if was_above and is_below:
            return True, "SELL"
        
        return False, "FLAT"
    
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
            self._ema_fast_cache.append(price)
            self._ema_slow_cache.append(price)
        
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
        
        # 1. Проверяем EMA Cross
        ema_cross, cross_direction = self._check_ema_cross(prices)
        
        # 2. Рассчитываем MACD
        macd, signal, histogram = self._calc_macd(prices)
        
        # 3. RSI
        rsi = self._calc_rsi(prices)
        
        # 4. Объём
        avg_vol = sum(volumes[-self.settings.volume_ma_period:]) / min(len(volumes), self.settings.volume_ma_period) if volumes else 1
        current_vol = volumes[-1] if volumes else 0
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        
        # 5. Тренд
        trend = self._get_trend(prices)
        
        # Подсчёт сигналов
        buy_count = 0
        sell_count = 0
        details = []
        
        # BUY сигналы
        # 1. EMA Cross (сильный)
        if cross_direction == "BUY" and trend == "UP":
            buy_count += 2  # Двойной вес
            details.append("EMA✅")
        else:
            details.append("EMA❌")
        
        # 2. MACD (сильный)
        if histogram is not None and histogram > 0:
            buy_count += 1
            details.append("MACD✅")
        elif histogram is not None:
            details.append("MACD❌")
        
        # 3. RSI фильтр
        if rsi is not None and rsi > self.settings.rsi_filter_low:
            buy_count += 1
            details.append(f"RSI({rsi:.0f})✅")
        else:
            details.append(f"RSI({rsi:.0f})❌" if rsi else "RSI❌")
        
        # 4. Объём
        if vol_ratio > self.settings.volume_threshold:
            buy_count += 1
            details.append(f"Vol({vol_ratio:.1f}x)✅")
        else:
            details.append(f"Vol({vol_ratio:.1f}x)❌")
        
        # SELL сигналы (зеркальные)
        if cross_direction == "SELL" and trend == "DOWN":
            sell_count += 2
        if histogram is not None and histogram < 0:
            sell_count += 1
        if rsi is not None and rsi < self.settings.rsi_filter_high:
            sell_count += 1
        if vol_ratio > self.settings.volume_threshold:
            sell_count += 1
        
        # Решение
        confidence = 0.0
        signal_type = SignalType.HOLD
        reason = ""
        
        if buy_count >= self.settings.entry_threshold:
            signal_type = SignalType.BUY
            confidence = min(buy_count / 4 + 0.1, 1.0)
            reason = f"🎯 BUY: {', '.join(details)} | Тренд: {trend}"
        elif sell_count >= self.settings.entry_threshold:
            signal_type = SignalType.SELL
            confidence = min(sell_count / 4 + 0.1, 1.0)
            reason = f"🎯 SELL: {', '.join(details)} | Тренд: {trend}"
        else:
            reason = f"⏸ {buy_count}/{self.settings.entry_threshold} BUY, {sell_count}/{self.settings.entry_threshold} SELL | {trend}"
        
        return ScalpSignal(
            signal_type=signal_type,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=confidence,
            reason=reason,
            indicators={
                'ema_cross': bool(ema_cross),
                'cross_dir': cross_direction,
                'macd': float(histogram) if histogram else 0.0,
                'rsi': float(rsi) if rsi else 50.0,
                'vol_ratio': float(vol_ratio),
                'trend': trend,
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
        direction: str = "BUY",
        trailing_stop_price: Optional[float] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None
    ) -> tuple:
        """Проверка закрытия позиции."""
        tp = take_profit if take_profit else self.settings.tp_percent
        sl = stop_loss if stop_loss else self.settings.sl_percent
        
        if direction == "BUY":
            profit_pct = (current_price - entry_price) / entry_price * 100
            
            # TP
            if profit_pct >= tp:
                return True, f"TP {profit_pct:.2f}%", None
            
            # Trailing SL
            if self.settings.use_trailing_sl and profit_pct >= self.settings.trailing_sl_activation:
                if trailing_stop_price is None:
                    new_ts = current_price * (1 - self.settings.trailing_sl_distance / 100)
                else:
                    new_ts = current_price * (1 - self.settings.trailing_sl_distance / 100)
                    if new_ts < trailing_stop_price:
                        new_ts = trailing_stop_price
                
                if current_price <= new_ts:
                    return True, f"TS {profit_pct:.2f}%", None
                
                return False, f"TS@{new_ts:.2f}({profit_pct:.2f}%)", new_ts
            
            # SL
            if profit_pct <= -sl:
                return True, f"SL {-sl:.2f}%", None
        
        else:  # SELL
            profit_pct = (entry_price - current_price) / entry_price * 100
            
            if profit_pct >= tp:
                return True, f"TP {profit_pct:.2f}%", None
            
            if profit_pct <= -sl:
                return True, f"SL {-sl:.2f}%", None
        
        return False, "", None
