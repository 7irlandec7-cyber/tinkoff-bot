"""
Profit Strategy - Максимальный винрейт с улучшениями
===================================================

Улучшения:
1. Адаптивный TP/SL на основе ATR
2. Фильтр волатильности (не входить во флэте)
3. Trailing Stop (улучшенный)
4. Trailing SL (поднимается за ценой)
5. Подтверждение 3 тика
6. Адаптивный размер позиции
"""
import logging
from typing import Optional, Dict, Tuple
from collections import deque

from .scalping_strategy import SignalType, ScalpSignal

logger = logging.getLogger(__name__)


class ProfitStrategy:
    """
    УЛУЧШЕННАЯ СТРАТЕГИЯ МАКСИМАЛЬНОГО ВИНРЕЙТА
    
    Входит когда 3/5 индикаторов совпадают + выполняются условия:
    - Фильтр волатильности: ATR > минимального порога
    - Trailing SL активен после 0.2% прибыли
    - 3 последовательных тика подтверждения
    """
    
    def __init__(
        self,
        tp_percent: float = 0.5,
        sl_percent: float = 0.2,
        entry_threshold: int = 3,  # 3/5 - интрадей баланс точности и частоты
        # RSI - ИНТРАДЕЙ оптимальные значения
        rsi_period: int = 14,
        rsi_oversold: float = 40,  # Ниже 40 = перепроданность (было 25)
        rsi_overbought: float = 60,  # Выше 60 = перекупленность (было 75)
        # Stochastic - ИНТРАДЕЙ оптимальные значения  
        stoch_period: int = 14,
        stoch_oversold: float = 30,  # Ниже 30 = перепроданность (было 15)
        stoch_overbought: float = 70,  # Выше 70 = перекупленность (было 85)
        # Order Book
        ob_depth: int = 10,
        ob_imbalance_threshold: float = 0.5,
        # Momentum
        min_momentum: float = 0.1,
        # History
        min_history: int = 10,
        # Подтверждение - 2 тика для интрадей (было 5)
        confirm_ticks: int = 2,
        # Фильтр волатильности - ОТКЛЮЧЁН для работы в спокойном рынке
        use_volatility_filter: bool = False,
        min_atr_percent: float = 0.0,  # Не используется
        # Trailing SL
        use_trailing_sl: bool = True,
        trailing_sl_activation: float = 0.1,  # Активируется при 0.1% прибыли
        trailing_sl_distance: float = 0.15,   # SL следует за ценой на 0.15%
        # Адаптивный TP
        use_adaptive_tp: bool = True,
        adaptive_tp_min: float = 0.15,
        adaptive_tp_max: float = 0.4,
    ):
        self.tp_percent = tp_percent
        self.sl_percent = sl_percent
        self.entry_threshold = entry_threshold
        
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        
        self.stoch_period = stoch_period
        self.stoch_oversold = stoch_oversold
        self.stoch_overbought = stoch_overbought
        
        self.ob_depth = ob_depth
        self.ob_imbalance_threshold = ob_imbalance_threshold
        self.min_momentum = min_momentum
        self.min_history = min_history
        self.confirm_ticks = confirm_ticks
        
        # Фильтр волатильности
        self.use_volatility_filter = use_volatility_filter
        self.min_atr_percent = min_atr_percent
        
        # Trailing SL
        self.use_trailing_sl = use_trailing_sl
        self.trailing_sl_activation = trailing_sl_activation
        self.trailing_sl_distance = trailing_sl_distance
        
        # Адаптивный TP
        self.use_adaptive_tp = use_adaptive_tp
        self.adaptive_tp_min = adaptive_tp_min
        self.adaptive_tp_max = adaptive_tp_max
        
        # Хранилище данных
        self.price_history: Dict[str, deque] = {}
        self.volume_history: Dict[str, deque] = {}
        self.orderbook_history: Dict[str, deque] = {}
        self.confirm_count: Dict[str, int] = {}
        self.last_signal: Dict[str, Optional[str]] = {}
        
        logger.info(
            f"🎯 PROFIT STRATEGY v2: TP={tp_percent}%, SL={sl_percent}%, Entry={entry_threshold}/5"
        )
        logger.info(
            f"   ⏱ Confirm={confirm_ticks} ticks | 📊 VolFilter={use_volatility_filter} | "
            f"TrailingSL={use_trailing_sl} | AdaptiveTP={use_adaptive_tp}"
        )
    
    def _calc_rsi(self, prices: list) -> float:
        """Расчёт RSI."""
        if len(prices) < self.rsi_period + 1:
            return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-self.rsi_period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-self.rsi_period:]]
        
        if not gains or not losses:
            return 50.0
        
        avg_gain = sum(gains) / len(gains)
        avg_loss = sum(losses) / len(losses)
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def _calc_stochastic(self, prices: list) -> Tuple[float, float]:
        """Расчёт Stochastic %K."""
        if len(prices) < self.stoch_period:
            return (50.0, 50.0)
        
        window = list(prices[-self.stoch_period:])
        low_min = min(window)
        high_max = max(window)
        
        if high_max == low_min:
            return (50.0, 50.0)
        
        k_raw = ((window[-1] - low_min) / (high_max - low_min)) * 100
        return (k_raw, k_raw)
    
    def _calc_momentum(self, prices: list) -> float:
        """Расчёт Momentum."""
        if len(prices) < 4:
            return 0.0
        prev_price = prices[-3]
        if prev_price == 0:
            return 0.0
        return ((prices[-1] - prev_price) / prev_price) * 100
    
    def _calc_atr(self, prices: list) -> float:
        """Расчёт ATR в % от цены."""
        if len(prices) < 14:
            return 0.0
        
        true_ranges = []
        for i in range(1, min(14, len(prices))):
            if prices[i-1] > 0:
                tr = abs(prices[i] - prices[i-1]) / prices[i-1] * 100
                true_ranges.append(tr)
        
        if not true_ranges:
            return 0.0
        
        return sum(true_ranges) / len(true_ranges)
    
    def _calc_ob_imbalance(self, orderbook: Optional[Dict]) -> Optional[float]:
        """Расчёт дисбаланса стакана."""
        if not orderbook:
            return None
        
        bids = orderbook.get('bids', [])[:self.ob_depth]
        asks = orderbook.get('asks', [])[:self.ob_depth]
        
        bid_vol = 0
        ask_vol = 0
        
        for b in bids:
            qty = b.get('quantity')
            if isinstance(qty, str):
                bid_vol += int(qty)
            else:
                bid_vol += int(qty or 0)
        
        for a in asks:
            qty = a.get('quantity')
            if isinstance(qty, str):
                ask_vol += int(qty)
            else:
                ask_vol += int(qty or 0)
        
        if bid_vol + ask_vol == 0:
            return 0.0
        
        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        return imbalance
    
    def _calc_ob_volume(self, orderbook: Optional[Dict]) -> Optional[float]:
        """Получить объём из стакана."""
        if not orderbook:
            return None
        
        bids = orderbook.get('bids', [])[:self.ob_depth]
        asks = orderbook.get('asks', [])[:self.ob_depth]
        
        bid_vol = 0
        ask_vol = 0
        
        for b in bids:
            qty = b.get('quantity')
            if isinstance(qty, str):
                bid_vol += int(qty)
            else:
                bid_vol += int(qty or 0)
        
        for a in asks:
            qty = a.get('quantity')
            if isinstance(qty, str):
                ask_vol += int(qty)
            else:
                ask_vol += int(qty or 0)
        
        return float(bid_vol + ask_vol)
    
    def _get_trend(self, prices: list) -> str:
        """Определение тренда."""
        if len(prices) < 20:
            return "FLAT"
        
        ma_short = sum(prices[-5:]) / 5
        ma_long = sum(prices[-20:]) / 20
        
        if ma_short > ma_long * 1.01:
            return "UP"
        elif ma_short < ma_long * 0.99:
            return "DOWN"
        return "FLAT"
    
    def _is_volatile_enough(self, atr_percent: float) -> Tuple[bool, str]:
        """Проверка достаточной волатильности для входа."""
        if not self.use_volatility_filter:
            return True, "VolFilter OFF"
        
        if atr_percent < self.min_atr_percent:
            return False, f"LowVol({atr_percent:.3f}% < {self.min_atr_percent}%)"
        return True, f"OK(ATR={atr_percent:.3f}%)"
    
    def _calc_adaptive_tp(self, atr_percent: float, direction: str) -> float:
        """Расчёт адаптивного TP на основе волатильности."""
        if not self.use_adaptive_tp:
            return self.tp_percent
        
        # TP пропорционален ATR
        adaptive_tp = atr_percent * 3  # 3x ATR
        
        # Ограничиваем
        return max(self.adaptive_tp_min, min(adaptive_tp, self.adaptive_tp_max))
    
    def _get_signal_strength(self, signal_type: str, rsi: float, stoch_k: float, 
                            imbalance: Optional[float], momentum: float, 
                            trend: str) -> Tuple[int, str, bool]:
        """Оценка силы сигнала с фильтром тренда."""
        imbalance_val = imbalance if imbalance is not None else 0.0
        
        count = 0
        details = []
        trend_ok = True
        
        # ФИЛЬТР ТРЕНДА
        if signal_type == "BUY" and trend == "DOWN":
            trend_ok = False
            details.append(f"Trend({trend})❌")
        elif signal_type == "SELL" and trend == "UP":
            trend_ok = False
            details.append(f"Trend({trend})❌")
        else:
            details.append(f"Trend({trend})✅")
        
        # RSI - строгий
        rsi_in_zone = False
        if signal_type == "BUY":
            if rsi < self.rsi_oversold:
                count += 1
                details.append(f"RSI({rsi:.0f})✅")
                rsi_in_zone = True
            elif rsi < 40:  # RSI движется к oversold
                count += 1
                details.append(f"RSI({rsi:.0f})→✅")
                rsi_in_zone = True
            else:
                details.append(f"RSI({rsi:.0f})❌")
        else:
            if rsi > self.rsi_overbought:
                count += 1
                details.append(f"RSI({rsi:.0f})✅")
                rsi_in_zone = True
            elif rsi > 60:  # RSI движется к overbought
                count += 1
                details.append(f"RSI({rsi:.0f})→✅")
                rsi_in_zone = True
            else:
                details.append(f"RSI({rsi:.0f})❌")
        
        # Stochastic - строгий
        if signal_type == "BUY":
            if stoch_k < self.stoch_oversold:
                count += 1
                details.append(f"Stoch({stoch_k:.0f})✅")
            elif stoch_k < 35:  # Stoch движется к oversold
                count += 1
                details.append(f"Stoch({stoch_k:.0f})→✅")
            else:
                details.append(f"Stoch({stoch_k:.0f})❌")
        else:
            if stoch_k > self.stoch_overbought:
                count += 1
                details.append(f"Stoch({stoch_k:.0f})✅")
            elif stoch_k > 65:  # Stoch движется к overbought
                count += 1
                details.append(f"Stoch({stoch_k:.0f})→✅")
            else:
                details.append(f"Stoch({stoch_k:.0f})❌")
        
        # Order Book
        if signal_type == "BUY":
            if imbalance_val > self.ob_imbalance_threshold:
                count += 1
                details.append(f"OB({imbalance_val:.2f})✅")
            else:
                details.append(f"OB({imbalance_val:.2f})❌")
        else:
            if imbalance_val < -self.ob_imbalance_threshold:
                count += 1
                details.append(f"OB({imbalance_val:.2f})✅")
            else:
                details.append(f"OB({imbalance_val:.2f})❌")
        
        # Momentum - интрадей умеренный
        if signal_type == "BUY":
            if momentum > self.min_momentum:  # Стандартный порог
                count += 1
                details.append(f"Mom({momentum:.2f}%)✅")
            else:
                details.append(f"Mom({momentum:.2f}%)❌")
        else:
            if momentum < -self.min_momentum:  # Стандартный порог
                count += 1
                details.append(f"Mom({momentum:.2f}%)✅")
            else:
                details.append(f"Mom({momentum:.2f}%)❌")
        
        # Volume - используем дисбаланс как прокси
        if abs(imbalance_val) > 0.3:
            count += 1
            details.append(f"Vol({abs(imbalance_val):.1f}x)✅")
        else:
            details.append(f"Vol({abs(imbalance_val):.1f}x)❌")
        
        return count, ", ".join(details), trend_ok
    
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
        
        # Инициализация истории
        if figi not in self.price_history:
            self.price_history[figi] = deque(maxlen=50)
            self.volume_history[figi] = deque(maxlen=20)
            self.orderbook_history[figi] = deque(maxlen=10)
            self.confirm_count[figi] = 0
            self.last_signal[figi] = None
        
        # Обновляем историю
        if price is not None:
            self.price_history[figi].append(price)
        
        ob_volume = self._calc_ob_volume(orderbook)
        if ob_volume is not None:
            self.volume_history[figi].append(ob_volume)
        
        if orderbook:
            self.orderbook_history[figi].append(orderbook)
        
        price_data = list(self.price_history[figi])
        vol_data = list(self.volume_history[figi])
        
        if len(price_data) < self.min_history:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=price_data[-1] if price_data else 0.0,
                confidence=0.0,
                reason=f"История ({len(price_data)}/{self.min_history})",
                indicators={}
            )
        
        current_price = price_data[-1]
        
        # Расчёт индикаторов
        rsi = self._calc_rsi(price_data)
        stoch_k, _ = self._calc_stochastic(price_data)
        imbalance = self._calc_ob_imbalance(orderbook)
        momentum = self._calc_momentum(price_data)
        trend = self._get_trend(price_data)
        atr = self._calc_atr(price_data)
        
        # Расчёт объёма
        if len(vol_data) >= 5:
            avg_vol = sum(vol_data[-5:]) / 5
            current_vol = vol_data[-1] if vol_data else 0
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
        else:
            vol_ratio = 1.0
        
        # Проверка волатильности
        is_volatile, vol_reason = self._is_volatile_enough(atr)
        
        # Оценка BUY и SELL сигналов
        buy_count, buy_details, buy_trend_ok = self._get_signal_strength(
            "BUY", rsi, stoch_k, imbalance, momentum, trend
        )
        sell_count, sell_details, sell_trend_ok = self._get_signal_strength(
            "SELL", rsi, stoch_k, imbalance, momentum, trend
        )
        
        # Проверка подтверждения для BUY
        if buy_count >= self.entry_threshold and buy_trend_ok and is_volatile:
            if self.last_signal.get(figi) == "BUY":
                self.confirm_count[figi] = self.confirm_count.get(figi, 0) + 1
            else:
                self.confirm_count[figi] = 1
                self.last_signal[figi] = "BUY"
            
            if self.confirm_count[figi] >= self.confirm_ticks:
                confidence = min(buy_count / 5 + 0.1, 1.0)
                adaptive_tp = self._calc_adaptive_tp(atr, "BUY")
                
                return ScalpSignal(
                    signal_type=SignalType.BUY,
                    figi=figi,
                    ticker=ticker,
                    price=current_price,
                    confidence=confidence,
                    reason=f"🎯 BUY: {buy_details} | {vol_reason}",
                    indicators={
                        'rsi': float(rsi),
                        'stoch': float(stoch_k),
                        'imbalance': float(imbalance or 0.0),
                        'momentum': float(momentum),
                        'vol_ratio': float(vol_ratio),
                        'trend': trend,
                        'atr': float(atr),
                        'signals_match': f"{buy_count}/5",
                        'tp_percent': adaptive_tp,
                        'sl_percent': self.sl_percent,
                        'trailing_sl': self.use_trailing_sl,
                        'trailing_sl_activation': self.trailing_sl_activation,
                    }
                )
            else:
                return ScalpSignal(
                    signal_type=SignalType.HOLD,
                    figi=figi,
                    ticker=ticker,
                    price=current_price,
                    confidence=buy_count / 5,
                    reason=f"⏸ BUY: {buy_count}/5 [Подтверждение {self.confirm_count[figi]}/{self.confirm_ticks}] | {vol_reason}",
                    indicators={
                        'rsi': float(rsi),
                        'stoch': float(stoch_k),
                        'atr': float(atr),
                        'trend': trend,
                    }
                )
        
        # Проверка подтверждения для SELL - ТОЛЬКО при нисходящем тренде!
        elif sell_count >= self.entry_threshold and sell_trend_ok and trend == "DOWN":
            # SELL только для закрытия существующих позиций
            if self.last_signal.get(figi) == "SELL":
                self.confirm_count[figi] = self.confirm_count.get(figi, 0) + 1
            else:
                self.confirm_count[figi] = 1
                self.last_signal[figi] = "SELL"
            
            if self.confirm_count[figi] >= self.confirm_ticks:
                confidence = min(sell_count / 5 + 0.1, 1.0)
                return ScalpSignal(
                    signal_type=SignalType.SELL,
                    figi=figi,
                    ticker=ticker,
                    price=current_price,
                    confidence=confidence,
                    reason=f"🎯 SELL: {sell_details} | {vol_reason}",
                    indicators={
                        'rsi': float(rsi),
                        'stoch': float(stoch_k),
                        'imbalance': float(imbalance or 0.0),
                        'momentum': float(momentum),
                        'vol_ratio': float(vol_ratio),
                        'trend': trend,
                        'atr': float(atr),
                        'signals_match': f"{sell_count}/5",
                    }
                )
            else:
                return ScalpSignal(
                    signal_type=SignalType.HOLD,
                    figi=figi,
                    ticker=ticker,
                    price=current_price,
                    confidence=sell_count / 5,
                    reason=f"⏸ SELL: {sell_count}/5 [Подтверждение {self.confirm_count[figi]}/{self.confirm_ticks}] | {vol_reason}",
                    indicators={
                        'rsi': float(rsi),
                        'stoch': float(stoch_k),
                        'atr': float(atr),
                        'trend': trend,
                    }
                )
        
        # HOLD
        self.confirm_count[figi] = 0
        self.last_signal[figi] = None
        
        best_match = max(buy_count, sell_count)
        best_type = "BUY" if buy_count >= sell_count else "SELL"
        
        return ScalpSignal(
            signal_type=SignalType.HOLD,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=best_match / 5,
            reason=f"⏸ {best_type}: {best_match}/5 | {vol_reason}",
            indicators={
                'rsi': float(rsi),
                'stoch': float(stoch_k),
                'imbalance': float(imbalance or 0.0),
                'momentum': float(momentum),
                'vol_ratio': float(vol_ratio),
                'trend': trend,
                'atr': float(atr),
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
        """
        Проверка закрытия позиции с улучшенным Trailing SL.
        
        Trailing SL работает так:
        - Активируется при прибыли >= trailing_sl_activation (0.2%)
        - Следует за ценой на расстоянии trailing_sl_distance (0.15%)
        - Никогда не отступает назад (только поднимается для BUY)
        """
        tp = take_profit if take_profit else self.tp_percent
        sl = stop_loss if stop_loss else self.sl_percent
        
        if direction == "BUY":
            profit_pct = (current_price - entry_price) / entry_price * 100
            
            # TP сработал
            if profit_pct >= tp:
                return True, f"TP {profit_pct:.2f}%", None
            
            # Trailing SL для BUY
            if self.use_trailing_sl and profit_pct >= self.trailing_sl_activation:
                if trailing_stop_price is None:
                    # Устанавливаем начальный trailing stop на уровне входа + расстояние
                    new_ts = entry_price * (1 + self.trailing_sl_distance / 100)
                else:
                    # Рассчитываем новый уровень trailing stop
                    # Он должен быть на trailing_sl_distance% ниже текущей цены
                    new_ts = current_price * (1 - self.trailing_sl_distance / 100)
                    
                    # Trailing stop НИКОГДА не опускается
                    if new_ts < trailing_stop_price:
                        new_ts = trailing_stop_price
                
                # Проверяем срабатывание trailing stop
                if current_price <= new_ts:
                    return True, f"TS {profit_pct:.2f}%", None
                
                # Возвращаем обновлённый trailing stop
                return False, f"TS@{new_ts:.2f}({profit_pct:.2f}%)", new_ts
            
            # Обычный SL
            if sl > 0 and profit_pct <= -sl:
                return True, f"SL {profit_pct:.2f}%", None
            
            return False, f"OK({profit_pct:.2f}%)", trailing_stop_price
        
        elif direction == "SELL":
            profit_pct = (entry_price - current_price) / entry_price * 100
            
            # TP сработал
            if profit_pct >= tp:
                return True, f"TP {profit_pct:.2f}%", None
            
            # Trailing SL для SHORT
            if self.use_trailing_sl and profit_pct >= self.trailing_sl_activation:
                if trailing_stop_price is None:
                    new_ts = entry_price * (1 - self.trailing_sl_distance / 100)
                else:
                    new_ts = current_price * (1 + self.trailing_sl_distance / 100)
                    
                    # Trailing stop НИКОГДА не поднимается
                    if new_ts > trailing_stop_price:
                        new_ts = trailing_stop_price
                
                if current_price >= new_ts:
                    return True, f"TS {profit_pct:.2f}%", None
                
                return False, f"TS@{new_ts:.2f}({profit_pct:.2f}%)", new_ts
            
            # Обычный SL
            if sl > 0 and profit_pct <= -sl:
                return True, f"SL {profit_pct:.2f}%", None
            
            return False, f"OK({profit_pct:.2f}%)", trailing_stop_price
        
        return False, "", None


def get_profit_strategy(tp: float = 0.5, sl: float = 0.2) -> ProfitStrategy:
    """Получить экземпляр Profit стратегии."""
    return ProfitStrategy(tp_percent=tp, sl_percent=sl)
