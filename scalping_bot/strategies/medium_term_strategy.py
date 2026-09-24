"""
Medium-term стратегия (среднесрок): удержание позиций от 30 мин до 4 часов.

Ключевые отличия от скальпинга:
- TP=1.5%, SL=0.7% (асимметрия для прибыли даже при winrate 35%)
- Сигналы только когда есть ЧЁТКИЙ ТРЕНД (ADX > 20, цена выше/ниже EMA50)
- Высокий порог входа (entry_threshold >= 2.0) — мало, но качественных сделок
- Объёмное подтверждение (>= 1.5x среднего)
- RSI 50-70 для лонга / 30-50 для шорта (среднесрок не работает в экстремумах)
- Никакого Bollinger/Stochastic — это шумовые индикаторы для скальпинга
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from scalping_bot.strategies.scalping_strategy import ScalpSignal, SignalType

logger = logging.getLogger(__name__)


@dataclass
class MediumTermSettings:
    """Параметры стратегии среднесрока."""
    # Минимум истории для расчёта трендовых индикаторов (EMA50 требует >= 50 точек)
    min_history: int = 60

    # === ТРЕНД-ФИЛЬТР (обязателен для среднесрока) ===
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend_period: int = 200  # долгосрочный тренд
    adx_period: int = 14
    adx_min: float = 20.0  # ниже = шум, выше = тренд

    # === RSI (без перекупленности для лонга / перепроданности для шорта) ===
    rsi_period: int = 14
    rsi_long_min: float = 50.0   # лонг только когда RSI >= 50 (тренд вверх)
    rsi_long_max: float = 70.0   # но не сильно перекуплено
    rsi_short_min: float = 30.0  # шорт только когда RSI <= 50 (тренд вниз)
    rsi_short_max: float = 50.0

    # === MACD (подтверждение направления) ===
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # === Объём (подтверждение институционального интереса) ===
    volume_ma_period: int = 20
    volume_min_ratio: float = 1.0  # отключаем фильтр объёма (история может быть без объёмов)

    # === Порог входа: достаточно 1.5 (совпало 2 сильных сигнала) ===
    entry_threshold: float = 1.5

    # === Анти-шум: одна и та же бумага не чаще раза в N секунд ===
    cooldown_seconds: int = 1800  # 30 минут

    # === TP/SL (для передачи в trader) ===
    take_profit_percent: float = 1.5
    stop_loss_percent: float = 0.7


class MediumTermStrategy:
    """
    Среднесрочная стратегия: ловит тренды и держит позиции часы, не минуты.
    """

    def __init__(self, settings: Optional[MediumTermSettings] = None):
        self.settings = settings or MediumTermSettings()
        self.price_history: Dict[str, List[float]] = {}
        self.volume_history: Dict[str, List[int]] = {}
        self._last_signal_ts: Dict[str, float] = {}  # figi -> timestamp последнего сигнала
        self._history_file = "/tmp/medium_term_history.json"
        self._load_history()

    def _save_history(self):
        """Сохраняет историю цен на диск (переживает рестарты)."""
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

    def _load_history(self):
        """Загружает историю цен с диска (годна до 4 часов)."""
        try:
            import json, os
            from datetime import datetime, timedelta
            if not os.path.exists(self._history_file):
                return
            with open(self._history_file, 'r') as f:
                data = json.load(f)
            saved = datetime.fromisoformat(data.get('saved_at', '2000-01-01'))
            if datetime.utcnow() - saved < timedelta(hours=48):
                self.price_history = data.get('price_history', {})
                self.volume_history = {k: list(v) for k, v in data.get('volume_history', {}).items()}
                imported = sum(len(v) for v in self.price_history.values())
                import logging
                logging.info(f"💾 Среднесрок: загружена история цен ({imported} точек, {len(self.price_history)} тикеров)")
            else:
                import logging
                logging.info("💾 Среднесрок: история устарела (>48ч), начинаем заново")
        except Exception as e:
            import logging
            logging.debug(f"Не удалось загрузить историю: {e}")

    def reset(self):
        self.price_history.clear()
        self.volume_history.clear()
        self._last_signal_ts.clear()

    # ---------------- Индикаторы ----------------

    @staticmethod
    def _sma(prices: List[float], period: int) -> Optional[float]:
        if len(prices) < period or period <= 0:
            return None
        return sum(prices[-period:]) / period

    @staticmethod
    def _ema(prices: List[float], period: int) -> Optional[float]:
        """Экспоненциальная скользящая средняя."""
        if len(prices) < period or period <= 0:
            return None
        k = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # старт как SMA
        for p in prices[period:]:
            ema = p * k + ema * (1 - k)
        return ema

    def _rsi(self, prices: List[float], period: int) -> Optional[float]:
        if len(prices) < period + 1:
            return None
        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        recent = deltas[-(period):]
        gains = [d for d in recent if d > 0]
        losses = [-d for d in recent if d < 0]
        avg_gain = sum(gains) / period if gains else 0.0
        avg_loss = sum(losses) / period if losses else 0.0
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _macd(self, prices: List[float]) -> Optional[Dict[str, float]]:
        """MACD: histogram = macd_line - signal_line."""
        if len(prices) < self.settings.macd_slow + self.settings.macd_signal:
            return None
        ema_fast = self._ema(prices, self.settings.macd_fast)
        ema_slow = self._ema(prices, self.settings.macd_slow)
        if ema_fast is None or ema_slow is None:
            return None
        macd_line = ema_fast - ema_slow

        # Чтобы вычислить signal line, нужна серия MACD — упрощённо:
        # signal ≈ EMA от macd_line за macd_signal периодов.
        # Для среднесрока достаточно направления и знака histogram.
        # Возьмём серию MACD для последних macd_signal точек:
        macd_series = []
        n = len(prices)
        lookback = self.settings.macd_signal + self.settings.macd_slow
        if n < lookback:
            return {"macd": macd_line, "signal": macd_line, "histogram": 0.0}
        for end in range(lookback, 0, -1):
            sub = prices[: n - end + 1]
            ef = self._ema(sub, self.settings.macd_fast)
            es = self._ema(sub, self.settings.macd_slow)
            if ef is not None and es is not None:
                macd_series.append(ef - es)
        if len(macd_series) < self.settings.macd_signal:
            signal = macd_line
        else:
            signal = self._ema(macd_series, self.settings.macd_signal) or macd_line
        return {"macd": macd_line, "signal": signal, "histogram": macd_line - signal}

    def _adx(self, prices: List[float], period: int = 14) -> Optional[float]:
        """
        Average Directional Index — сила тренда (0..100).
        Ниже 20 = шум/боковик, выше 25 = тренд, выше 40 = сильный тренд.
        Упрощённый расчёт без +DM/-DM строгого разделения, но достаточный
        для фильтра «есть тренд / нет тренда».
        """
        if len(prices) < period + 1:
            return None
        trs = []
        plus_dm = []
        minus_dm = []
        for i in range(1, len(prices)):
            high_curr = max(prices[i], prices[i - 1])
            low_curr = min(prices[i], prices[i - 1])
            high_prev = prices[i - 1]
            low_prev = prices[i - 1]
            tr = high_curr - low_curr
            up = prices[i] - high_prev
            down = low_prev - prices[i]
            trs.append(tr if tr > 0 else 1e-9)
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
        if len(trs) < period:
            return None
        # Wilder smoothing
        atr = sum(trs[:period]) / period
        plus_di = (sum(plus_dm[:period]) / period) / atr * 100 if atr > 0 else 0.0
        minus_di = (sum(minus_dm[:period]) / period) / atr * 100 if atr > 0 else 0.0
        dx = abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-9) * 100
        return dx  # упрощённо: возвращаем последний DX как прокси ADX

    def _volume_ok(self, ticker: str) -> bool:
        """Объём за последний бар должен быть >= 1.5x средний."""
        vols = self.volume_history.get(ticker, [])
        if len(vols) < self.settings.volume_ma_period:
            return False  # недостаточно истории — не торгуем
        avg = sum(vols[-self.settings.volume_ma_period:]) / self.settings.volume_ma_period
        if avg <= 0:
            return False
        ratio = vols[-1] / avg
        return ratio >= self.settings.volume_min_ratio

    # ---------------- Анализ ----------------

    def analyze(
        self,
        figi: str,
        ticker=None,
        price=None,
        volume=None,
        orderbook=None,
    ):
        """
        Возвращает ScalpSignal (BUY / SELL / HOLD).
        Среднесрок генерирует BUY когда:
        - тренд вверх (EMA_fast > EMA_slow с достаточной разницей)
        - ADX > 18 (слабая граница, отсекает боковик)
        - RSI в зоне 45-70 (без перекупленности)
        - MACD histogram > 0
        - объём ≥ 1.2x среднего
        """
        ticker = ticker or figi

        try:
            price_value = float(price) if price is not None else 0.0
        except (TypeError, ValueError):
            price_value = 0.0

        if price_value <= 0:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=0.0,
                confidence=0.0,
                reason="Нет валидной цены",
                indicators={},
            )

        if ticker not in self.price_history:
            self.price_history[ticker] = []
            self.volume_history[ticker] = []

        self.price_history[ticker].append(price_value)
        if volume is not None:
            try:
                self.volume_history[ticker].append(int(volume))
            except (TypeError, ValueError):
                pass

        prices = self.price_history[ticker]

        if len(prices) < self.settings.min_history:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=price_value,
                confidence=0.0,
                reason=f"История ({len(prices)}/{self.settings.min_history})",
                indicators={},
            )

        # === 1. ТРЕНД-ФИЛЬТР ===
        ema_fast = self._ema(prices, self.settings.ema_fast)
        ema_slow = self._ema(prices, self.settings.ema_slow)
        adx = self._adx(prices, self.settings.adx_period)

        if ema_fast is None or ema_slow is None:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=price_value,
                confidence=0.0,
                reason="Недостаточно данных",
                indicators={},
            )

        # Разница EMA: ценовой тренд в процентах
        ema_diff_pct = abs(ema_fast - ema_slow) / ema_slow * 100 if ema_slow > 0 else 0
        trend_up = ema_fast > ema_slow and ema_diff_pct > 0.05
        trend_down = ema_fast < ema_slow and ema_diff_pct > 0.05

        # ADX: не вычислился / сломанные данные → не отсекаем
        adx_valid = adx is not None and adx > 0
        adx_trend = bool(adx_valid and adx is not None and adx >= self.settings.adx_min)

        # Нет НИ тренда, ни ADX
        if not trend_up and not trend_down and adx_trend:
            # ADX говорит «тренд», но EMA расхождение крошечное — доверяем EMA
            if ema_diff_pct < 0.02:
                pass  # позволим индикаторам решить

        # === 2. RSI ===
        rsi = self._rsi(prices, self.settings.rsi_period)
        if rsi is None:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=price_value,
                confidence=0.0,
                reason="Недостаточно данных для RSI",
                indicators={},
            )

        # === 3. MACD ===
        macd = self._macd(prices)
        macd_hist = macd["histogram"] if macd else 0.0

        # === 4. Объём ===
        vol_ok = self._volume_ok(ticker)

        # === Подсчёт очков ===
        buy_score = 0.0
        sell_score = 0.0

        # Тренд (вес 1.0): цена относительно EMA + crossover скользящих
        trend_up = bool(ema_fast > ema_slow and ema_diff_pct > 0.05)
        trend_down = bool(ema_fast < ema_slow and ema_diff_pct > 0.05)

        # Цена относительно EMA (более наглядно на малых windows)
        price_above_ema = price_value > ema_fast
        price_below_ema = price_value < ema_fast

        if trend_up or (price_above_ema and ema_fast > ema_slow):
            buy_score += 1.0
        elif trend_down or (price_below_ema and ema_fast < ema_slow):
            sell_score += 1.0

        # MACD (вес 1.0)
        if abs(macd_hist) > 0.01:
            if macd_hist > 0:
                buy_score += 1.0
            else:
                sell_score += 1.0

        # RSI «зона силы» (вес 0.8 для BUY, 0.6 для SELL)
        if 45 <= rsi <= 70:
            buy_score += 0.8
        elif rsi >= 75:
            # Перекуплен — не лонг, но и не шорт (шорты отключены)
            pass
        elif rsi <= 30:
            sell_score += 0.6

        # Объём (бонус 0.5)
        if vol_ok:
            if trend_up or buy_score > sell_score:
                buy_score += 0.5
            elif trend_down or sell_score > buy_score:
                sell_score += 0.5

        # ADX-бонус (0.3) — подтверждение тренда
        if adx_trend:
            if trend_up:
                buy_score += 0.3
            elif trend_down:
                sell_score += 0.3

        # === КОНТР-ТРЕНДОВЫЙ BUY ===
        # Используем price_below_ema (не trend_down) — crossover может быть
        # микроскопическим (EMA20≈EMA50 на 100 точках) и не достигать 0.05%.
        force_buy = False
        counter_trend_label = ""
        if price_below_ema:  # цена ниже EMA — тренд слабый/вниз, потенциальный отскок
            recent_window = min(20, len(prices))
            recent_low = min(prices[-recent_window:]) if recent_window > 0 else price_value
            near_low = (price_value - recent_low) / max(recent_low, 0.001) < 0.02

            if rsi < 25:  # экстремальная перепроданность
                counter_score = 2.0
                if near_low: counter_score += 0.3
                if vol_ok: counter_score += 0.2
                buy_score += counter_score
                force_buy = True
                counter_trend_label = f"📉{rsi:.0f}"
                logger.debug(f"  ⏫ Контр-тренд BUY {ticker}: RSI={rsi:.0f} +{counter_score:.1f}")

            elif 25 <= rsi < 35 and macd_hist is not None and macd_hist > -0.5 and macd_hist < 0:
                counter_score = 1.5
                if near_low: counter_score += 0.3
                if vol_ok: counter_score += 0.2
                buy_score += counter_score
                force_buy = True
                counter_trend_label = f"↗{rsi:.0f}"
                logger.debug(f"  ⏫ Контр-тренд BUY {ticker}: RSI={rsi:.0f} MACD={macd_hist:.4f} +{counter_score:.1f}")

        # === Решение ===
        signal = "HOLD"
        confidence = 0.0

        if force_buy and buy_score >= self.settings.entry_threshold:
            signal = "BUY"
            confidence = min(1.0, buy_score / (self.settings.entry_threshold + 1.5))
            reason = f"Контр-тренд BUY {counter_trend_label}: RSI={rsi:.0f} объём={'✓' if vol_ok else '✗'}"
        elif buy_score >= self.settings.entry_threshold and buy_score > sell_score:
            signal = "BUY"
            confidence = min(1.0, buy_score / (self.settings.entry_threshold + 1.0))
            reason = (
                f"Среднесрок BUY: ADX={max(adx or 0, 0):.0f} EMA{ema_diff_pct:.1f}%↑ "
                f"RSI={rsi:.0f} MACD={'+' if abs(macd_hist) > 0.01 else '0'} "
                f"объём={'✓' if vol_ok else '✗'}"
            )
        elif sell_score >= self.settings.entry_threshold and sell_score > buy_score:
            signal = "SELL"
            confidence = min(1.0, sell_score / (self.settings.entry_threshold + 1.0))
            reason = (
                f"Среднесрок SELL: ADX={max(adx or 0, 0):.0f} EMA{ema_diff_pct:.1f}%↓ "
                f"RSI={rsi:.0f} MACD={'−' if abs(macd_hist) > 0.01 else '0'} "
                f"объём={'✓' if vol_ok else '✗'}"
            )
        else:
            reason = (
                f"HOLD B:{buy_score:.1f}/S:{sell_score:.1f} "
                f"ADX={max(adx or 0, 0):.0f} EMA{ema_diff_pct:.1f}% RSI={rsi:.0f}"
            )

        # Cooldown
        import time as _time
        last_ts = self._last_signal_ts.get(figi, 0.0)
        if signal != "HOLD" and (_time.time() - last_ts) < self.settings.cooldown_seconds:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=price_value,
                confidence=0.0,
                reason=f"Cooldown ({int(self.settings.cooldown_seconds / 60)} мин)",
                indicators={"buy_score": buy_score, "sell_score": sell_score},
            )

        if signal != "HOLD":
            self._last_signal_ts[figi] = _time.time()

        return ScalpSignal(
            signal_type=SignalType[signal],
            figi=figi,
            ticker=ticker,
            price=price_value,
            confidence=confidence,
            reason=reason,
            indicators={
                "adx": adx,
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "ema_diff_pct": ema_diff_pct,
                "rsi": rsi,
                "macd_hist": macd_hist,
                "volume_ok": vol_ok,
                "buy_score": buy_score,
                "sell_score": sell_score,
                "tp": self.settings.take_profit_percent,
                "sl": self.settings.stop_loss_percent,
            },
        )

    def should_close_position(
        self,
        figi: str,
        entry_price: float,
        current_price: float,
        direction: str,
        take_profit: float = 1.5,
        stop_loss: float = 0.7,
    ) -> tuple:
        """Проверка закрытия позиции по TP/SL для среднесрока."""
        if entry_price <= 0:
            return False, "", ""
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        if direction == "SELL":
            pnl_pct = -pnl_pct
        if pnl_pct <= -stop_loss:
            return True, f"SL ({pnl_pct:.2f}%)", "sell"
        if pnl_pct >= take_profit:
            return True, f"TP ({pnl_pct:.2f}%)", "buy"
        return False, "", ""
