"""
Multi-Indicator скальпинг стратегия.
Комбинирует 7 индикаторов для генерации сигналов в любых рыночных условиях.
"""
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MultiIndicatorSettings:
    """Настройки мульти-индикаторной стратегии."""
    # RSI
    rsi_oversold: float = 50     # RSI < 50 для BUY (мягче чем 45)
    rsi_overbought: float = 50   # RSI > 50 для SELL
    rsi_period: int = 5

    # MA
    ma_fast: int = 5
    ma_slow: int = 20
    ma_period: int = 20

    # EMA (экспоненциальные скользящие средние)
    ema_fast: int = 8
    ema_slow: int = 21

    # Bollinger Bands
    bb_period: int = 20
    bb_std: float = 1.5

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # Stochastic RSI
    stoch_rsi_period: int = 14
    stoch_rsi_k: int = 3
    stoch_rsi_d: int = 3

    # Объём
    volume_ma_period: int = 20
    volume_threshold: float = 1.0

    # Волатильность
    atr_period: int = 14
    volatility_breakout_threshold: float = 1.5

    # Order book
    orderbook_imbalance_threshold: float = 1.3

    # История
    min_history: int = 15

    # Порог входа - мягче
    entry_threshold: float = 1.0

    # TP/SL
    tp_percent: float = 0.30
    sl_percent: float = 0.20

    use_trailing_sl: bool = False


class MultiIndicatorScalpingStrategy:
    """
    Мульти-индикаторная скальпинг стратегия с 7 индикаторами:
    1. RSI - классический индикатор перекупленности
    2. MA/EMA Crossover - трендовый сигнал
    3. Bollinger Bands - волатильность и экстремумы
    4. MACD - схождение/расхождение MA
    5. Stochastic RSI - чувствительный осциллятор
    6. Volume Confirmation - подтверждение объёмом
    7. Order Book Imbalance - перевес bid/ask
    """

    def __init__(self, settings: Optional[MultiIndicatorSettings] = None):
        self.settings = settings or MultiIndicatorSettings()
        self.price_history: Dict[str, List[float]] = {}
        self.volume_history: Dict[str, List[int]] = {}
        self._history_file = "/tmp/multi_history.json"
        self.load_history()  # Загружаем историю при старте

    def reset(self):
        self.price_history.clear()
        self.volume_history.clear()

    def save_history(self):
        """Сохраняет историю цен на диск (для переживания рестартов)."""
        try:
            import json
            from datetime import datetime
            data = {
                'price_history': self.price_history,
                'volume_history': {k: list(v) for k, v in self.volume_history.items()},
                'saved_at': datetime.utcnow().isoformat()
            }
            with open(self._history_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            import logging
            logging.debug(f"Не удалось сохранить историю: {e}")

    def load_history(self):
        """Загружает историю цен с диска."""
        try:
            import json
            import os
            if os.path.exists(self._history_file):
                with open(self._history_file, 'r') as f:
                    data = json.load(f)
                # Только если данные не старше 4 часов
                from datetime import datetime, timedelta
                saved = datetime.fromisoformat(data.get('saved_at', '2000-01-01'))
                if datetime.utcnow() - saved < timedelta(hours=4):
                    self.price_history = data.get('price_history', {})
                    self.volume_history = {k: list(v) for k, v in data.get('volume_history', {}).items()}
                    import logging
                    logging.info(f"💾 Загружена история цен: {sum(len(v) for v in self.price_history.values())} точек")
                else:
                    import logging
                    logging.info(f"💾 История устарела (>4ч), начинаем заново")
        except Exception as e:
            import logging
            logging.debug(f"Не удалось загрузить историю: {e}")

    # ---------- Индикаторы ----------

    def _calculate_rsi(self, prices: List[float], period: int = 5) -> Optional[float]:
        """RSI."""
        if len(prices) < period + 1:
            return None
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        if sum(losses) == 0:
            return 100.0 if sum(gains) > 0 else 50.0
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_sma(self, prices: List[float], period: int) -> Optional[float]:
        """Простая скользящая средняя."""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    def _calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """Экспоненциальная скользящая средняя."""
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _calculate_bollinger_bands(
        self, prices: List[float], period: int = 20, std_mult: float = 1.5
    ) -> Optional[Dict[str, float]]:
        """Bollinger Bands - возвращает upper, middle, lower."""
        if len(prices) < period:
            return None
        sma = sum(prices[-period:]) / period
        variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
        std = variance ** 0.5
        return {
            "upper": sma + std_mult * std,
            "middle": sma,
            "lower": sma - std_mult * std,
        }

    def _calculate_macd(
        self, prices: List[float], fast: int = 12, slow: int = 26, signal_period: int = 9
    ) -> Optional[Dict[str, float]]:
        """MACD - возвращает macd, signal, histogram."""
        if len(prices) < slow + signal_period:
            return None
        ema_fast = self._calculate_ema(prices, fast)
        ema_slow = self._calculate_ema(prices, slow)
        if ema_fast is None or ema_slow is None:
            return None
        macd_line = ema_fast - ema_slow

        # Сигнальная линия - EMA от MACD
        macd_history = []
        for i in range(slow, len(prices) + 1):
            subset = prices[:i]
            ef = self._calculate_ema(subset, fast)
            es = self._calculate_ema(subset, slow)
            if ef is not None and es is not None:
                macd_history.append(ef - es)

        if len(macd_history) < signal_period:
            return None
        signal_line = self._calculate_ema(macd_history, signal_period)
        if signal_line is None:
            return None
        return {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": macd_line - signal_line,
        }

    def _calculate_stoch_rsi(
        self, prices: List[float], period: int = 14, k: int = 3, d: int = 3
    ) -> Optional[Dict[str, float]]:
        """Stochastic RSI."""
        if len(prices) < period + k + d:
            return None

        # Сначала считаем RSI для каждой точки
        rsi_values = []
        for i in range(period + 1, len(prices) + 1):
            rsi = self._calculate_rsi(prices[:i], period)
            if rsi is not None:
                rsi_values.append(rsi)

        if len(rsi_values) < k:
            return None

        # Stochastic от RSI
        recent_rsi = rsi_values[-k:]
        min_rsi = min(recent_rsi)
        max_rsi = max(recent_rsi)
        if max_rsi == min_rsi:
            stoch_k = 50.0
        else:
            stoch_k = ((rsi_values[-1] - min_rsi) / (max_rsi - min_rsi)) * 100

        # %D - SMA от %K
        if len(rsi_values) < k + d:
            return {"k": stoch_k, "d": stoch_k}
        k_values = []
        for i in range(k, len(rsi_values) + 1):
            subset = rsi_values[i - k:i]
            mn = min(subset)
            mx = max(subset)
            if mx == mn:
                k_values.append(50.0)
            else:
                k_values.append(((rsi_values[i - 1] - mn) / (mx - mn)) * 100)
        if len(k_values) < d:
            return {"k": stoch_k, "d": stoch_k}
        stoch_d = sum(k_values[-d:]) / d
        return {"k": stoch_k, "d": stoch_d}

    def _calculate_atr(self, prices: List[float], period: int = 14) -> Optional[float]:
        """Average True Range (упрощённый - используя только цены)."""
        if len(prices) < period + 1:
            return None
        ranges = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        return sum(ranges[-period:]) / period

    # ---------- Анализ ----------

    def analyze(
        self,
        figi: str,
        ticker=None,
        price=None,
        volume=None,
        orderbook=None,
    ):
        """Анализ и генерация сигнала."""
        ticker = ticker or figi

        if ticker not in self.price_history:
            self.price_history[ticker] = []
            self.volume_history[ticker] = []

        # ВАЖНО: не добавляем в историю некорректные цены (0 / None / отрицательные),
        # иначе RSI/MA/Bollinger считаются по мусору и дают ложные сигналы.
        try:
            price_value = float(price) if price is not None else 0.0
        except (TypeError, ValueError):
            price_value = 0.0

        if price_value > 0:
            self.price_history[ticker].append(price_value)
            if volume is not None:
                self.volume_history[ticker].append(volume)

        prices = list(self.price_history[ticker])
        volumes = list(self.volume_history[ticker])

        # Импорт для ответа
        from scalping_bot.strategies.scalping_strategy import ScalpSignal, SignalType

        # Нет валидной текущей цены -> торговать нельзя (защита от "SELL @ 0.00")
        if price_value <= 0:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=0.0,
                confidence=0.0,
                reason="Нет валидной цены (стакан пуст / инструмент не торгуется)",
                indicators={},
            )

        if len(prices) < self.settings.min_history:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=price or 0,
                confidence=0.0,
                reason=f"История ({len(prices)}/{self.settings.min_history})",
                indicators={},
            )

        # Расчёт всех индикаторов
        rsi = self._calculate_rsi(prices, self.settings.rsi_period)
        sma_fast = self._calculate_sma(prices, self.settings.ma_fast)
        sma_slow = self._calculate_sma(prices, self.settings.ma_slow)
        ema_fast = self._calculate_ema(prices, self.settings.ema_fast)
        ema_slow = self._calculate_ema(prices, self.settings.ema_slow)
        bb = self._calculate_bollinger_bands(prices, self.settings.bb_period, self.settings.bb_std)
        macd = self._calculate_macd(prices, self.settings.macd_fast, self.settings.macd_slow, self.settings.macd_signal)
        stoch_rsi = self._calculate_stoch_rsi(prices, self.settings.stoch_rsi_period, self.settings.stoch_rsi_k, self.settings.stoch_rsi_d)
        atr = self._calculate_atr(prices, self.settings.atr_period)

        # Объём
        vol_ma = sum(volumes[-self.settings.volume_ma_period:]) / self.settings.volume_ma_period if len(volumes) >= self.settings.volume_ma_period else 1
        vol_ratio = volumes[-1] / vol_ma if vol_ma > 0 else 1.0

        # Отклонение от MA
        price_vs_ma = ((prices[-1] - sma_slow) / sma_slow * 100) if sma_slow else 0

        # Momentum
        momentum = ((prices[-1] - prices[-5]) / prices[-5] * 100) if len(prices) >= 5 and prices[-5] != 0 else 0

        # Order book imbalance (нейтральное значение 1.0 если не получен)
        orderbook_imbalance = 1.0
        orderbook_available = False
        if orderbook:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            if bids and asks:
                bid_vol = sum(b.get('quantity', 0) for b in bids[:5])
                ask_vol = sum(a.get('quantity', 0) for a in asks[:5])
                if ask_vol > 0:
                    orderbook_imbalance = bid_vol / ask_vol
                    orderbook_available = True

        # ---- Подсчёт очков ----
        buy_score = 0.0
        sell_score = 0.0

        # 1. RSI (вес 1.0)
        if rsi is not None:
            # Жёсткие пороги для исключения шума при нейтральном RSI
            if rsi < 40:
                buy_score += 1.0
            elif rsi < 45:
                buy_score += 0.5
            elif rsi > 60:
                sell_score += 1.0
            elif rsi > 55:
                sell_score += 0.5
            # RSI 45-55 - нейтральная зона, не даёт сигналов

        # 2. MA Crossover (вес 1.0) — только при достаточной разнице
        if sma_fast and sma_slow:
            ma_diff_pct = abs(sma_fast - sma_slow) / sma_slow * 100
            if ma_diff_pct > 0.1:  # Разница > 0.1%
                if sma_fast > sma_slow:
                    buy_score += 0.7
                else:
                    sell_score += 0.7
        if ema_fast and ema_slow:
            ema_diff_pct = abs(ema_fast - ema_slow) / ema_slow * 100
            if ema_diff_pct > 0.1:  # Разница > 0.1%
                if ema_fast > ema_slow:
                    buy_score += 0.5
                else:
                    sell_score += 0.5

        # 3. Bollinger Bands (вес 0.8)
        if bb:
            if prices[-1] < bb["lower"]:
                buy_score += 0.8
            elif prices[-1] > bb["upper"]:
                sell_score += 0.8

        # 4. MACD (вес 1.0)
        if macd:
            hist = macd["histogram"]
            if hist > 0.01:  # Порог чтобы избежать шума на 0
                buy_score += 1.0
            elif hist < -0.01:
                sell_score += 1.0
            # Иначе - нейтрально, не даём очков

        # 5. Stochastic RSI (вес 0.8)
        if stoch_rsi:
            if stoch_rsi["k"] < 20 and stoch_rsi["k"] > stoch_rsi["d"]:
                buy_score += 0.8
            elif stoch_rsi["k"] > 80 and stoch_rsi["k"] < stoch_rsi["d"]:
                sell_score += 0.8

        # 6. Volume Confirmation (вес 0.5)
        if vol_ratio >= self.settings.volume_threshold:
            if buy_score > sell_score:
                buy_score += 0.5
            elif sell_score > buy_score:
                sell_score += 0.5

        # 7. Order Book Imbalance (вес 0.7) — ТОЛЬКО если стакан получен!
        if orderbook_available:
            if orderbook_imbalance > self.settings.orderbook_imbalance_threshold:
                buy_score += 0.7
            elif orderbook_imbalance < 1 / self.settings.orderbook_imbalance_threshold:
                sell_score += 0.7

        # 8. Momentum (вес 0.5)
        if momentum < -0.3:
            buy_score += 0.5
        elif momentum > 0.3:
            sell_score += 0.5

        # 9. Volatility breakout (вес 0.5)
        if atr and len(prices) >= 3:
            price_change = abs(prices[-1] - prices[-2])
            if price_change > atr * self.settings.volatility_breakout_threshold:
                if prices[-1] > prices[-2]:
                    buy_score += 0.5
                else:
                    sell_score += 0.5

        # Определение итогового сигнала
        max_score = max(buy_score, sell_score)
        total_indicators = 7.5

        if max_score >= self.settings.entry_threshold:
            if buy_score > sell_score:
                signal = "BUY"
                confidence = min(buy_score / total_indicators, 1.0)
            elif sell_score > buy_score:
                signal = "SELL"
                confidence = min(sell_score / total_indicators, 1.0)
            else:
                signal = "HOLD"
                confidence = max_score / total_indicators
        else:
            signal = "HOLD"
            confidence = max_score / total_indicators

        indicators = {
            "rsi": float(rsi) if rsi is not None else 50.0,
            "momentum": momentum,
            "vol_ratio": float(vol_ratio),
            "price_vs_ma": float(price_vs_ma),
            "ma": float(sma_slow) if sma_slow else 0,
            "bb_upper": float(bb["upper"]) if bb else 0,
            "bb_lower": float(bb["lower"]) if bb else 0,
            "macd_hist": float(macd["histogram"]) if macd else 0,
            "stoch_k": float(stoch_rsi["k"]) if stoch_rsi else 50,
            "stoch_d": float(stoch_rsi["d"]) if stoch_rsi else 50,
            "ob_imbalance": float(orderbook_imbalance),
            "atr": float(atr) if atr else 0,
            "tp_percent": self.settings.tp_percent,
            "sl_percent": self.settings.sl_percent,
            "buy_score": buy_score,
            "sell_score": sell_score,
        }

        if signal == "BUY":
            macd_str = f"{macd['histogram']:+.2f}" if macd else "n/a"
            stoch_str = f"{stoch_rsi['k']:.0f}" if stoch_rsi else "n/a"
            reason = f"Multi-BUY RSI({rsi:.0f}) MACD({macd_str}) Stoch({stoch_str}) OB({orderbook_imbalance:.1f})"
        elif signal == "SELL":
            macd_str = f"{macd['histogram']:+.2f}" if macd else "n/a"
            stoch_str = f"{stoch_rsi['k']:.0f}" if stoch_rsi else "n/a"
            reason = f"Multi-SELL RSI({rsi:.0f}) MACD({macd_str}) Stoch({stoch_str}) OB({orderbook_imbalance:.1f})"
        else:
            reason = f"HOLD RSI({rsi:.0f}) B:{buy_score:.1f} S:{sell_score:.1f}"

        return ScalpSignal(
            signal_type=SignalType[signal],
            figi=figi,
            ticker=ticker,
            price=prices[-1] if prices else 0,
            confidence=confidence,
            reason=reason,
            indicators=indicators,
        )

    def __del__(self):
        """Сохраняет историю при завершении."""
        try:
            self.save_history()
        except Exception:
            pass

    def should_close_position(
        self,
        figi: str,
        entry_price: float,
        current_price: float,
        direction: str,
        take_profit: float = 0.30,
        stop_loss: float = 0.20,
    ) -> tuple:
        """Проверка закрытия позиции."""
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        if direction == "SELL":
            pnl_pct = -pnl_pct

        if pnl_pct <= -stop_loss:
            return True, f"SL ({pnl_pct:.2f}%)", "sell"
        if pnl_pct >= take_profit:
            return True, f"TP ({pnl_pct:.2f}%)", "buy"
        return False, "", ""

    def get_indicators_display(self, indicators: Dict) -> str:
        rsi = indicators.get("rsi", 50)
        vol = indicators.get("vol_ratio", 1.0)
        ob = indicators.get("ob_imbalance", 1.0)
        bs = indicators.get("buy_score", 0)
        ss = indicators.get("sell_score", 0)
        return f"RSI({rsi:.0f}) Vol({vol:.1f}x) OB({ob:.1f}) B:{bs:.1f}/S:{ss:.1f}"
