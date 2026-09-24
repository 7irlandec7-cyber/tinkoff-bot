"""
Advanced Strategy Module - Комбинированная стратегия с улучшениями
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
from collections import deque
import statistics

from .scalping_strategy import SignalType, ScalpSignal

logger = logging.getLogger(__name__)


@dataclass
class TrailingStop:
    """Трейлинг-стоп для позиции."""
    entry_price: float
    current_high: float = 0.0
    stop_price: float = 0.0
    trailing_percent: float = 0.3  # 0.3% за ценой
    lock_percent: float = 0.5     # Начинаем трейл когда прибыль > 0.5%
    activated: bool = False
    
    def update(self, current_price: float) -> Tuple[bool, str]:
        """
        Обновить трейлинг-стоп.
        Returns: (should_stop, reason)
        """
        if not self.activated:
            # Проверяем, пора ли активировать
            profit_pct = (current_price - self.entry_price) / self.entry_price * 100
            if profit_pct >= self.lock_percent:
                self.activated = True
                self.current_high = current_price
                self.stop_price = current_price * (1 - self.trailing_percent / 100)
        
        if self.activated:
            # Обновляем high
            if current_price > self.current_high:
                self.current_high = current_price
                # Поднимаем стоп
                self.stop_price = current_price * (1 - self.trailing_percent / 100)
            
            # Проверяем срабатывание
            if current_price <= self.stop_price:
                profit = (current_price - self.entry_price) / self.entry_price * 100
                return True, f"Трейл-стоп: {profit:.2f}%"
        
        return False, ""
    
    def reset(self, entry_price: float):
        """Сбросить для новой позиции."""
        self.entry_price = entry_price
        self.current_high = entry_price
        self.stop_price = entry_price * 0.99  # Начальный стоп на 1% ниже
        self.activated = False


@dataclass
class PositionState:
    """Расширенное состояние позиции."""
    figi: str
    ticker: str
    entry_price: float
    quantity: int
    direction: str  # BUY/SELL
    entry_time: datetime = field(default_factory=datetime.now)
    
    # Trailing stop
    trailing_stop: Optional[TrailingStop] = None
    
    # Сигналы от стратегий
    signals: Dict[str, float] = field(default_factory=dict)  # strategy -> confidence
    
    # Метаданные
    signal_expire_time: Optional[datetime] = None
    volume_at_entry: float = 0.0
    
    def add_signal(self, strategy: str, confidence: float):
        """Добавить сигнал от стратегии."""
        self.signals[strategy] = confidence
    
    def get_agreed_direction(self) -> Optional[str]:
        """Получить согласованное направление от всех стратегий."""
        if not self.signals:
            return None
        
        buy_count = sum(1 for v in self.signals.values() if v > 0)
        sell_count = sum(1 for v in self.signals.values() if v < 0)
        
        if buy_count >= 2:
            return "BUY"
        elif sell_count >= 2:
            return "SELL"
        return None
    
    def is_expired(self) -> bool:
        """Проверить, не истёк ли сигнал."""
        if self.signal_expire_time is None:
            return False
        return datetime.now() > self.signal_expire_time


class AdvancedMultiStrategy:
    """
    Продвинутая мульти-стратегия с улучшениями:
    - Trailing Stop
    - Динамический размер позиции
    - Таймфрейм-комбинация
    - Корреляция с индексом
    - Адаптивный TP/SL
    - Фильтр объёма
    - Экстренный стоп при гэпах
    - Время экспирации сигнала
    """
    
    def __init__(
        self,
        # Trailing stop
        trailing_percent: float = 0.3,
        lock_percent: float = 0.5,
        # Risk management
        risk_per_trade: float = 0.5,  # % от портфеля
        max_position_percent: float = 20.0,  # Макс % портфеля в одной поз.
        # Volume filter
        volume_multiplier: float = 1.5,
        # Signal expiry
        signal_expiry_seconds: int = 120,
        # Emergency stop
        gap_threshold_percent: float = 2.0,
        # Correlation
        correlation_threshold: float = 0.6,
    ):
        self.trailing_percent = trailing_percent
        self.lock_percent = lock_percent
        self.risk_per_trade = risk_per_trade
        self.max_position_percent = max_position_percent
        self.volume_multiplier = volume_multiplier
        self.signal_expiry_seconds = signal_expiry_seconds
        self.gap_threshold_percent = gap_threshold_percent
        self.correlation_threshold = correlation_threshold
        
        # История для всех инструментов
        self.price_histories: Dict[str, deque] = {}
        self.volume_histories: Dict[str, deque] = {}
        self.multi_timeframe: Dict[str, Dict[int, deque]] = {}  # figi -> {tf_minutes -> deque}
        
        # Индекс для корреляции
        self.index_figi = "BBG004S681P8"  # MOEX Index (IMOEX)
        self.index_history: deque = deque(maxlen=100)
        
        logger.info(
            f"📊 Advanced Multi-Strategy:\n"
            f"   Trailing: {trailing_percent}%, Lock: {lock_percent}%\n"
            f"   Risk: {risk_per_trade}%, Max pos: {max_position_percent}%\n"
            f"   Volume filter: {volume_multiplier}x\n"
            f"   Signal expiry: {signal_expiry_seconds}s\n"
            f"   Gap stop: {gap_threshold_percent}%"
        )
    
    def _get_history(self, figi: str) -> deque:
        if figi not in self.price_histories:
            self.price_histories[figi] = deque(maxlen=50)
        return self.price_histories[figi]
    
    def _get_volume_history(self, figi: str) -> deque:
        if figi not in self.volume_histories:
            self.volume_histories[figi] = deque(maxlen=20)
        return self.volume_histories[figi]
    
    def _get_tf_history(self, figi: str, tf_minutes: int) -> deque:
        if figi not in self.multi_timeframe:
            self.multi_timeframe[figi] = {}
        if tf_minutes not in self.multi_timeframe[figi]:
            self.multi_timeframe[figi][tf_minutes] = deque(maxlen=100)
        return self.multi_timeframe[figi][tf_minutes]
    
    def _check_correlation_with_index(self, figi: str, direction: str) -> float:
        """
        Проверить корреляцию направления инструмента с индексом.
        Returns: correlation_score (-1 to 1)
        """
        if not self.index_history or len(self.index_history) < 5:
            return 0.0  # Недостаточно данных
        
        if figi not in self.price_histories or len(self.price_histories[figi]) < 5:
            return 0.0
        
        # Считаем изменения за последние N баров
        n = min(5, len(self.index_history))
        index_changes = []
        ticker_changes = []
        
        index_list = list(self.index_history)
        ticker_list = list(self.price_histories[figi])
        
        for i in range(n):
            idx = len(index_list) - n + i
            if idx > 0:
                idx_change = (index_list[idx] - index_list[idx-1]) / index_list[idx-1]
                tk_change = (ticker_list[idx] - ticker_list[idx-1]) / ticker_list[idx-1]
                index_changes.append(idx_change)
                ticker_changes.append(tk_change)
        
        if not index_changes:
            return 0.0
        
        # Простая корреляция
        if not index_changes or not ticker_changes:
            return 0.0
        avg_idx = sum(index_changes) / len(index_changes)
        avg_tk = sum(ticker_changes) / len(ticker_changes)
        
        # Если индекс растёт, а мы хотим шорт - плохо
        if direction == "BUY" and avg_idx < -0.001:
            return -0.5  # Штраф
        if direction == "SELL" and avg_idx > 0.001:
            return -0.5  # Штраф
        
        return 0.0  # Нет штрафа
    
    def _get_adaptive_tp_sl(
        self,
        figi: str,
        base_tp: float,
        base_sl: float,
        direction: str
    ) -> Tuple[float, float]:
        """
        Рассчитать адаптивный TP/SL на основе волатильности.
        """
        history = self._get_history(figi)
        if len(history) < 10:
            return base_tp, base_sl
        
        # Рассчитываем волатильность
        changes = []
        prices = list(history)
        for i in range(1, len(prices)):
            if prices[i-1] == 0:
                continue
            change = abs((prices[i] - prices[i-1]) / prices[i-1] * 100)
            changes.append(change)
        
        avg_volatility = sum(changes[-10:]) / min(10, len(changes))
        
        # Если волатильность высокая - расширяем
        if avg_volatility > 0.5:
            tp_multiplier = 1.3
            sl_multiplier = 1.3
        elif avg_volatility < 0.2:
            tp_multiplier = 0.8
            sl_multiplier = 0.8
        else:
            tp_multiplier = 1.0
            sl_multiplier = 1.0
        
        return base_tp * tp_multiplier, base_sl * sl_multiplier
    
    def _check_volume(self, figi: str, volume: float) -> bool:
        """Проверить объём."""
        vol_hist = self._get_volume_history(figi)
        if len(vol_hist) < 5:
            return True  # Недостаточно данных, пропускаем
        
        avg_volume = sum(list(vol_hist)) / len(vol_hist)
        return volume >= avg_volume * self.volume_multiplier
    
    def _check_gap(self, figi: str, entry_price: float, current_price: float) -> bool:
        """Проверить гэп."""
        if entry_price <= 0:
            return False
        
        gap = abs(current_price - entry_price) / entry_price * 100
        return gap >= self.gap_threshold_percent
    
    def analyze(
        self,
        figi: str,
        ticker: str,
        current_price: float,
        volume: float = 0,
        orderbook: Optional[Dict] = None,
    ) -> ScalpSignal:
        """
        Анализ с учётом всех улучшений.
        """
        # Добавляем в историю
        history = self._get_history(figi)
        history.append(current_price)
        
        vol_hist = self._get_volume_history(figi)
        if volume > 0:
            vol_hist.append(volume)
        
        # Многотаймфрейм
        for tf in [5, 15, 60]:  # 5min, 15min, 1hour
            tf_hist = self._get_tf_history(figi, tf)
            # Упрощённо: добавляем каждые N вызовов
            if len(tf_hist) == 0 or (len(history) % (tf // 5) == 0):
                tf_hist.append(current_price)
        
        indicators = {}
        
        # Недостаточно данных
        if len(history) < 10:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason=f"Набор истории ({len(history)}/10)",
                indicators=indicators
            )
        
        # Проверка объёма
        if not self._check_volume(figi, volume):
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.1,
                reason=f"Низкий объём: {volume:.0f}",
                indicators=indicators
            )
        
        # Базовые метрики
        momentum = self._get_momentum(history)
        volatility = self._get_volatility(history)
        trend = self._get_trend(history)
        
        # Многотаймфрейм подтверждение
        tf_confirm = self._get_tf_confirmation(figi)
        
        indicators["momentum"] = momentum
        indicators["volatility"] = volatility
        indicators["trend"] = trend
        indicators["tf_confirm"] = tf_confirm
        
        # Сигнал
        signal_type = SignalType.HOLD
        confidence = 0.0
        reason = ""
        
        if momentum > 0.01 and trend >= 0 and tf_confirm >= 0:
            # BUY - агрессивный вход (снижены пороги)
            confidence = min(0.5 + abs(momentum) * 0.3 + tf_confirm * 0.1, 0.95)
            signal_type = SignalType.BUY
            reason = f"Momentum+Binance TF confirm={tf_confirm}"
        
        elif momentum < -0.01 and trend <= 0 and tf_confirm >= 0:
            # SELL - агрессивный вход (снижены пороги)
            confidence = min(0.5 + abs(momentum) * 0.3 + tf_confirm * 0.1, 0.95)
            signal_type = SignalType.SELL
            reason = f"Momentum-Binance TF confirm={tf_confirm}"
        
        if signal_type == SignalType.HOLD:
            reason = f"M={momentum:.2f}, T={trend:.2f}, V={volatility:.2f}"
        
        return ScalpSignal(
            signal_type=signal_type,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=confidence,
            reason=reason,
            indicators=indicators
        )
    
    def _get_momentum(self, history: deque) -> float:
        if len(history) < 5:
            return 0.0
        changes = []
        prices = list(history)
        for i in range(1, min(6, len(prices))):
            if prices[-i-1] == 0:
                continue
            change = (prices[-i] - prices[-i-1]) / prices[-i-1] * 100
            changes.append(change)
        return sum(changes) / len(changes) if changes else 0.0
    
    def _get_volatility(self, history: deque) -> float:
        if len(history) < 5:
            return 0.0
        changes = []
        prices = list(history)
        for i in range(1, min(6, len(prices))):
            if prices[-i-1] == 0:
                continue
            change = abs((prices[-i] - prices[-i-1]) / prices[-i-1] * 100)
            changes.append(change)
        return sum(changes) / len(changes) if changes else 0.0
    
    def _get_trend(self, history: deque) -> float:
        if len(history) < 10:
            return 0.0
        prices = list(history)
        first = prices[0]
        last = prices[-1]
        if first == 0:
            return 0.0
        return (last - first) / first * 100
    
    def _get_tf_confirmation(self, figi: str) -> int:
        """
        Подсчёт подтверждений от разных таймфреймов.
        Returns: количество TF согласных с направлением
        """
        confirmations = 0
        
        # Простая логика: если цена растёт на TF - это бычье подтверждение
        for tf in [5, 15, 60]:
            tf_hist = self._get_tf_history(figi, tf)
            if len(tf_hist) >= 3:
                prev_price = list(tf_hist)[-3]
                if prev_price != 0:
                    recent_trend = (list(tf_hist)[-1] - prev_price) / prev_price * 100
                    if abs(recent_trend) > 0.1:  # Есть движение
                        confirmations += 1
        
        return confirmations
    
    def create_trailing_stop(self, entry_price: float) -> TrailingStop:
        """Создать трейлинг-стоп для позиции."""
        return TrailingStop(
            entry_price=entry_price,
            current_high=entry_price,
            stop_price=entry_price * (1 - 0.5 / 100),  # Начальный стоп на 0.5% ниже
            trailing_percent=self.trailing_percent,
            lock_percent=self.lock_percent,
            activated=False
        )
    
    def calculate_position_size(
        self,
        portfolio_value: float,
        price: float,
        stop_loss_percent: float
    ) -> int:
        """
        Рассчитать размер позиции с учётом риска.
        Риск на сделку = risk_per_trade % от портфеля
        """
        # Риск в рублях
        risk_amount = portfolio_value * (self.risk_per_trade / 100)
        
        # Риск на акцию
        risk_per_share = price * (stop_loss_percent / 100)
        
        if risk_per_share <= 0:
            return 1
        
        # Размер позиции
        quantity = int(risk_amount / risk_per_share)
        
        # Ограничиваем максимальным % от портфеля
        max_qty = int(portfolio_value * (self.max_position_percent / 100) / price)
        quantity = min(quantity, max_qty)
        
        return max(1, quantity)
    
    def should_close_position(
        self,
        figi: str,
        entry_price: float,
        current_price: float,
        direction: str,
        take_profit: float = 0.8,
        stop_loss: float = 1.0,
        trailing_stop: Optional[TrailingStop] = None
    ) -> Tuple[bool, str]:
        """
        Проверить закрытие с учётом всех факторов.
        """
        if entry_price <= 0 or current_price <= 0:
            return False, ""
        
        pnl_percent = (current_price - entry_price) / entry_price * 100
        
        # 1. Проверка гэпа
        if self._check_gap(figi, entry_price, current_price):
            return True, f"ГЭП: {abs(pnl_percent):.2f}%"
        
        # 2. Trailing stop
        if trailing_stop:
            should_stop, reason = trailing_stop.update(current_price)
            if should_stop:
                return True, f"Trailing: {reason}"
        
        # 3. Адаптивный TP/SL
        adaptive_tp, adaptive_sl = self._get_adaptive_tp_sl(figi, take_profit, stop_loss, direction)
        
        # 4. Базовые проверки
        if direction == "BUY":
            if pnl_percent < -adaptive_sl:
                return True, f"SL: {pnl_percent:.2f}%"
            if pnl_percent > adaptive_tp:
                return True, f"TP: {pnl_percent:.2f}%"
        else:  # SELL
            if pnl_percent > adaptive_sl:
                return True, f"SL: {pnl_percent:.2f}%"
            if pnl_percent < -adaptive_tp:
                return True, f"TP: {pnl_percent:.2f}%"
        
        return False, ""
    
    def reset(self, figi: str):
        """Сбросить историю."""
        if figi in self.price_histories:
            del self.price_histories[figi]
        if figi in self.volume_histories:
            del self.volume_histories[figi]


def get_advanced_strategy() -> AdvancedMultiStrategy:
    """Получить экземпляр продвинутой стратегии."""
    return AdvancedMultiStrategy(
        trailing_percent=0.3,
        lock_percent=0.5,
        risk_per_trade=0.5,
        max_position_percent=20.0,
        volume_multiplier=1.5,
        signal_expiry_seconds=120,
        gap_threshold_percent=2.0,
    )
