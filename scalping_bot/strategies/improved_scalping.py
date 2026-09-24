"""
Улучшенная скальпинг стратегия.
Более сбалансированные условия входа для стабильных сделок.
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ImprovedScalpingSettings:
    """Настройки улучшенной скальпинг стратегии."""
    # RSI - более чувствительные пороги
    rsi_oversold: float = 45    # RSI < 45 для BUY (было 40)
    rsi_overbought: float = 55  # RSI > 55 для SELL (было 60)
    rsi_period: int = 5
    
    # Объём - смягчённый фильтр
    volume_ma_period: int = 20
    volume_threshold: float = 1.2  # Объём > 1.2x среднего (было 1.5)
    
    # История
    min_history: int = 20
    
    # Вход: 1.0 - любой значимый индикатор
    entry_threshold: float = 1.0
    
    # TP/SL - динамические
    tp_percent: float = 0.40   # TP 0.4%
    sl_percent: float = 0.20   # SL 0.2%
    
    # Trailing stop отключён
    use_trailing_sl: bool = False


class ImprovedScalpingStrategy:
    """
    Улучшенная скальпинг стратегия с 3 индикаторами:
    1. RSI Extreme - RSI < 45 для BUY, RSI > 55 для SELL
    2. Price deviation from MA - цена отклоняется от средней
    3. Volume confirmation - объём подтверждает движение
    """
    
    def __init__(self, settings: Optional[ImprovedScalpingSettings] = None):
        self.settings = settings or ImprovedScalpingSettings()
        self.price_history: Dict[str, List[float]] = {}
        self.volume_history: Dict[str, List[int]] = {}
        self.rsi_history: Dict[str, List[float]] = {}
        self.ma_history: Dict[str, Optional[float]] = {}
    
    def reset(self):
        """Сброс состояния."""
        self.price_history.clear()
        self.volume_history.clear()
        self.rsi_history.clear()
        self.ma_history.clear()
    
    def _calculate_rsi(self, prices: List[float], period: int = 5) -> Optional[float]:
        """Расчёт RSI."""
        if len(prices) < period + 1:
            return None
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        
        if not losses or sum(losses) == 0:
            return 100.0 if sum(gains) > 0 else 50.0
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def _calculate_ma(self, prices: List[float], period: int = 20) -> Optional[float]:
        """Расчёт скользящей средней."""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period
    
    def analyze(
        self,
        figi: str,
        ticker=None,
        price=None,
        volume=None,
        orderbook=None
    ):
        """
        Анализ бумаги и генерация сигнала.
        
        Returns:
            ScalpSignal with signal_type, confidence, and indicators
        """
        ticker = ticker or figi
        
        # Инициализация истории если нужно
        if ticker not in self.price_history:
            self.price_history[ticker] = []
            self.volume_history[ticker] = []
            self.rsi_history[ticker] = []
            self.ma_history[ticker] = None
        
        # Добавляем новые данные в историю
        if price is not None:
            self.price_history[ticker].append(price)
        if volume is not None:
            self.volume_history[ticker].append(volume)
        
        # Получаем историю цен и объёмов
        prices = list(self.price_history[ticker])
        volumes = list(self.volume_history[ticker])
        
        if len(prices) < self.settings.min_history:
            from scalping_bot.strategies.scalping_strategy import ScalpSignal, SignalType
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=price or 0,
                confidence=0.0,
                reason=f"История ({len(prices)}/{self.settings.min_history})",
                indicators={}
            )
        
        # Расчёт индикаторов
        rsi = self._calculate_rsi(prices, self.settings.rsi_period)
        if rsi is not None:
            self.rsi_history[ticker].append(rsi)
        
        ma = self._calculate_ma(prices, self.settings.volume_ma_period)
        self.ma_history[ticker] = ma
        
        # RSI изменение (для определения тренда)
        rsi_history = self.rsi_history.get(ticker, [])
        rsi_change = 0
        if len(rsi_history) >= 2:
            rsi_change = rsi_history[-1] - rsi_history[-2]
        
        # Отклонение от MA
        if ma and prices[-1] < ma:
            price_vs_ma = (prices[-1] - ma) / ma * 100  # % ниже MA
        elif ma:
            price_vs_ma = (prices[-1] - ma) / ma * 100  # % выше MA
        else:
            price_vs_ma = 0
        
        # Соотношение объёма к среднему
        vol_ma = sum(volumes[-self.settings.volume_ma_period:]) / self.settings.volume_ma_period if len(volumes) >= self.settings.volume_ma_period else 1
        vol_ratio = volumes[-1] / vol_ma if vol_ma > 0 else 1.0
        
        # Импульс (изменение цены за последние N баров)
        momentum = 0
        if len(prices) >= 5 and prices[-5] != 0:
            momentum = (prices[-1] - prices[-5]) / prices[-5] * 100
        
        # Подсчёт индикаторов
        buy_score = 0.0
        sell_score = 0.0
        
        # 1. RSI Extreme (вес 1.0)
        if rsi is not None:
            if rsi < self.settings.rsi_oversold:
                buy_score += 1.0
            elif rsi > self.settings.rsi_overbought:
                sell_score += 1.0
            elif rsi < 50:
                buy_score += 0.5
            elif rsi > 50:
                sell_score += 0.5
        
        # 2. Price vs MA (вес 0.8) - покупаем когда ниже MA, продаём когда выше
        if price_vs_ma < -0.5:  # Цена на 0.5% ниже MA
            buy_score += 0.8
        elif price_vs_ma > 0.5:  # Цена на 0.5% выше MA
            sell_score += 0.8
        elif price_vs_ma < 0:
            buy_score += 0.3
        elif price_vs_ma > 0:
            sell_score += 0.3
        
        # 3. Volume confirmation (вес 0.7)
        if vol_ratio >= self.settings.volume_threshold:
            if buy_score > sell_score:
                buy_score += 0.7
            elif sell_score > buy_score:
                sell_score += 0.7
        
        # 4. Momentum (вес 0.5)
        if momentum < -0.3:
            buy_score += 0.5
        elif momentum > 0.3:
            sell_score += 0.5
        
        # Определение сигнала
        max_score = max(buy_score, sell_score)
        total_indicators = 3.0  # RSI, MA, Volume, Momentum = 4 индикатора
        
        if max_score >= self.settings.entry_threshold:
            if buy_score > sell_score:
                confidence = min(buy_score / total_indicators, 1.0)
                signal = "BUY"
            elif sell_score > buy_score:
                confidence = min(sell_score / total_indicators, 1.0)
                signal = "SELL"
            else:
                signal = "HOLD"
                confidence = 0.0
        else:
            signal = "HOLD"
            confidence = max_score / total_indicators
        
        indicators = {
            "rsi": float(rsi) if rsi is not None else 50.0,
            "rsi_change": rsi_change,
            "momentum": momentum,
            "vol_ratio": float(vol_ratio),
            "price_vs_ma": float(price_vs_ma),
            "ma": float(ma) if ma else 0,
            "tp_percent": self.settings.tp_percent,
            "sl_percent": self.settings.sl_percent,
        }
        
        # Создаём причину для логов
        if signal == "BUY":
            reason = f"RSI({rsi:.0f}<{self.settings.rsi_oversold}), MA({price_vs_ma:+.1f}%), Vol({vol_ratio:.1f}x)"
        elif signal == "SELL":
            reason = f"RSI({rsi:.0f}>{self.settings.rsi_overbought}), MA({price_vs_ma:+.1f}%), Vol({vol_ratio:.1f}x)"
        else:
            reason = f"RSI({rsi:.0f}), MA({price_vs_ma:+.1f}%), Vol({vol_ratio:.1f}x)"
        
        # Импортируем здесь чтобы избежать циклической зависимости
        from scalping_bot.strategies.scalping_strategy import ScalpSignal, SignalType
        
        return ScalpSignal(
            signal_type=SignalType[signal],
            figi=figi,
            ticker=ticker,
            price=prices[-1] if prices else 0,
            confidence=confidence,
            reason=reason,
            indicators=indicators
        )
    
    def should_close_position(
        self,
        figi: str,
        entry_price: float,
        current_price: float,
        direction: str,
        take_profit: float = 0.4,
        stop_loss: float = 0.2
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
        
        return False, "", ""
    
    def get_indicators_display(self, indicators: Dict) -> str:
        """Форматирование индикаторов для отображения."""
        rsi = indicators.get("rsi", 50)
        vol = indicators.get("vol_ratio", 1.0)
        mom = indicators.get("momentum", 0)
        ma_diff = indicators.get("price_vs_ma", 0)
        
        parts = []
        parts.append(f"RSI({rsi:.0f})")
        parts.append(f"Vol({vol:.1f}x)")
        parts.append(f"Mom({mom:+.1f}%)")
        parts.append(f"MA({ma_diff:+.1f}%)")
        
        return " | ".join(parts)
