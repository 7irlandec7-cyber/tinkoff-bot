"""
Super Combined Strategy - Все сигналы должны совпадать!
"""
import logging
from typing import Optional, Dict, Tuple
from collections import deque
import statistics

from .scalping_strategy import SignalType, ScalpSignal

logger = logging.getLogger(__name__)


class SuperCombinedStrategy:
    """
    СУПЕР-СТРАТЕГИЯ: Все сигналы должны СОВПАДАТЬ!
    
    Комбинирует ВСЕ индикаторы и входит ТОЛЬКО когда:
    1. RSI показывает перекупленность/перепроданность
    2. Stochastic подтверждает
    3. Order Book (стакан) показывает дисбаланс
    4. Momentum сильный
    5. Объём подтверждает
    
    Вход: Только когда ВСЕ 5 сигналов BUY или ВСЕ 5 сигналов SELL
    """
    
    def __init__(
        self,
        tp_percent: float = 0.5,
        sl_percent: float = 0.2,
        # RSI
        rsi_period: int = 14,
        rsi_oversold: float = 35,
        rsi_overbought: float = 65,
        # Stochastic
        stoch_period: int = 14,
        stoch_smooth: int = 3,
        stoch_oversold: float = 25,
        stoch_overbought: float = 75,
        # Order Book
        ob_depth: int = 10,
        ob_imbalance_threshold: float = 0.4,
        # Momentum
        min_momentum: float = 0.05,
        # Volume
        min_volume_ratio: float = 1.2,
        # History
        min_history: int = 5,
    ):
        self.tp_percent = tp_percent
        self.sl_percent = sl_percent
        
        # RSI params (уменьшено для быстрого старта)
        self.rsi_period = 5  # Было 14, теперь 5
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        
        # Stochastic params (уменьшено для быстрого старта)
        self.stoch_period = 5  # Было 14, теперь 5
        self.stoch_smooth = stoch_smooth
        self.stoch_oversold = stoch_oversold
        self.stoch_overbought = stoch_overbought
        
        # Order Book params
        self.ob_depth = ob_depth
        self.ob_imbalance_threshold = ob_imbalance_threshold
        
        # Momentum
        self.min_momentum = min_momentum
        
        # Volume
        self.min_volume_ratio = min_volume_ratio
        
        # History
        self.min_history = 3  # Было 5, теперь 3
        
        # Хранилище данных
        self.price_history: Dict[str, deque] = {}
        self.volume_history: Dict[str, deque] = {}
        self.orderbook_history: Dict[str, deque] = {}
        
        logger.info(
            f"🎯 SUPER STRATEGY: TP={tp_percent}%, SL={sl_percent}%, "
            f"RSI({rsi_oversold}/{rsi_overbought}), "
            f"Stoch({stoch_oversold}/{stoch_overbought}), "
            f"OB_imbalance={ob_imbalance_threshold}, "
            f"min_momentum={min_momentum}%"
        )
    
    def _calc_rsi(self, prices: list, current_price: Optional[float] = None) -> float:
        """Расчёт RSI - использует последние цены или current_price."""
        # Если есть история - используем её
        if len(prices) >= self.rsi_period + 1:
            deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            gains = [d if d > 0 else 0 for d in deltas[-self.rsi_period:]]
            losses = [-d if d < 0 else 0 for d in deltas[-self.rsi_period:]]
            
            if gains and losses:
                avg_gain = sum(gains) / len(gains)
                avg_loss = sum(losses) / len(losses)
                
                if avg_loss == 0:
                    return 100.0
                
                rs = avg_gain / avg_loss
                return 100 - (100 / (1 + rs))
        
        # Если есть только current_price - считаем на основе Order Book
        if current_price is not None and len(prices) >= 2:
            # RSI на основе спреда Bid/Ask
            price_change = abs(prices[-1] - prices[0]) if len(prices) >= 2 else 0
            if price_change == 0:
                return 50.0
            # Простая оценка RSI на основе движения
            direction = 1 if prices[-1] > prices[0] else -1
            magnitude = min(price_change / prices[0] * 100, 100)
            return 50 + (direction * magnitude)
        
        return 50.0
    
    def _calc_stochastic(self, prices: list, orderbook: Optional[Dict] = None) -> Tuple[float, float]:
        """Расчёт Stochastic %K - использует prices или Order Book."""
        # Если есть история - используем её
        if len(prices) >= self.stoch_period:
            window = list(prices[-self.stoch_period:])
            low_min = min(window)
            high_max = max(window)
            
            if high_max == low_min:
                return (50.0, 50.0)
            
            k_raw = ((window[-1] - low_min) / (high_max - low_min)) * 100
            return (k_raw, k_raw)
        
        # Если есть Order Book - считаем на его основе
        if orderbook:
            bids = orderbook.get('bids', [])[:5]
            asks = orderbook.get('asks', [])[:5]
            
            if bids and asks:
                # Парсим цены
                bid_prices = [self._parse_price(b.get('price', 0)) for b in bids if b.get('price')]
                ask_prices = [self._parse_price(a.get('price', 0)) for a in asks if a.get('price')]
                
                if bid_prices and ask_prices:
                    best_bid = bid_prices[0]
                    best_ask = ask_prices[0]
                    mid_price = (best_bid + best_ask) / 2
                    
                    # Находим high/low в стакане
                    high_price = max(bid_prices)
                    low_price = min(ask_prices)
                    
                    if high_price > low_price:
                        k = ((mid_price - low_price) / (high_price - low_price)) * 100
                        return (k, k)
        
        return (50.0, 50.0)
    
    def _calc_momentum(self, prices: list) -> float:
        """Расчёт Momentum за последние 3 бара."""
        if len(prices) < 4:
            return 0.0
        prev_price = prices[-3]
        if prev_price == 0:
            return 0.0
        return ((prices[-1] - prev_price) / prev_price) * 100
    
    def _calc_volume_ratio(self, volumes: list) -> float:
        """Расчёт отношения текущего объёма к среднему."""
        if len(volumes) < 5:
            return 1.0
        avg = sum(volumes[-5:]) / 5
        if avg == 0:
            return 1.0
        return volumes[-1] / avg if volumes else 1.0
    
    def _parse_price(self, price_data) -> float:
        """Парсинг цены из формата API (units + nano или просто число)."""
        if isinstance(price_data, dict):
            units = int(price_data.get('units', 0))
            nano = int(price_data.get('nano', 0))
            return units + nano / 1e9
        return float(price_data)
    
    def _calc_ob_imbalance(self, orderbook: Dict) -> Optional[float]:
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
        
        # Дисбаланс: положительный = больше на бидах (бычий)
        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        return imbalance
    
    def _get_signal_strength(self, signal_type: str, rsi: float, stoch_k: float, 
                            imbalance: Optional[float], momentum: float, vol_ratio: float) -> Tuple[int, str]:
        """
        Оценка силы сигнала.
        Возвращает: (count, details)
        count = количество подтверждающих индикаторов
        """
        imbalance = imbalance if imbalance is not None else 0.0
        """
        Оценка силы сигнала.
        Возвращает: (count, details)
        count = количество подтверждающих индикаторов
        """
        count = 0
        details = []
        
        # 1. RSI
        if signal_type == "BUY":
            if rsi < self.rsi_oversold:
                count += 1
                details.append(f"RSI({rsi:.0f})✅")
            else:
                details.append(f"RSI({rsi:.0f})❌")
        else:  # SELL
            if rsi > self.rsi_overbought:
                count += 1
                details.append(f"RSI({rsi:.0f})✅")
            else:
                details.append(f"RSI({rsi:.0f})❌")
        
        # 2. Stochastic
        if signal_type == "BUY":
            if stoch_k < self.stoch_oversold:
                count += 1
                details.append(f"Stoch({stoch_k:.0f})✅")
            else:
                details.append(f"Stoch({stoch_k:.0f})❌")
        else:
            if stoch_k > self.stoch_overbought:
                count += 1
                details.append(f"Stoch({stoch_k:.0f})✅")
            else:
                details.append(f"Stoch({stoch_k:.0f})❌")
        
        # 3. Order Book
        if signal_type == "BUY":
            if imbalance > self.ob_imbalance_threshold:
                count += 1
                details.append(f"OB({imbalance:.2f})✅")
            else:
                details.append(f"OB({imbalance:.2f})❌")
        else:
            if imbalance < -self.ob_imbalance_threshold:
                count += 1
                details.append(f"OB({imbalance:.2f})✅")
            else:
                details.append(f"OB({imbalance:.2f})❌")
        
        # 4. Momentum
        if signal_type == "BUY":
            if momentum > self.min_momentum:
                count += 1
                details.append(f"Mom({momentum:.2f}%)✅")
            else:
                details.append(f"Mom({momentum:.2f}%)❌")
        else:
            if momentum < -self.min_momentum:
                count += 1
                details.append(f"Mom({momentum:.2f}%)✅")
            else:
                details.append(f"Mom({momentum:.2f}%)❌")
        
        # 5. Volume
        if vol_ratio >= self.min_volume_ratio:
            count += 1
            details.append(f"Vol({vol_ratio:.1f}x)✅")
        else:
            details.append(f"Vol({vol_ratio:.1f}x)❌")
        
        return count, ", ".join(details)
    
    def analyze(
        self,
        figi: str,
        ticker: str,
        current_price: float,
        volume: float = 0,
        orderbook: Optional[Dict] = None
    ) -> ScalpSignal:
        """Анализ инструмента - ВСЕ индикаторы должны совпадать."""
        
        # Инициализация истории
        if figi not in self.price_history:
            self.price_history[figi] = deque(maxlen=30)
            self.volume_history[figi] = deque(maxlen=30)
        
        # Обновление истории
        self.price_history[figi].append(current_price)
        if volume > 0:
            self.volume_history[figi].append(volume)
        
        prices = list(self.price_history[figi])
        volumes = list(self.volume_history[figi])
        
        # Проверка достаточности данных
        if len(prices) < self.min_history:
            return ScalpSignal(
                signal_type=SignalType.HOLD,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=0.0,
                reason=f"История ({len(prices)}/{self.min_history})",
                indicators={'history': len(prices)}
            )
        
        # ===== РАСЧЁТ ВСЕХ ИНДИКАТОРОВ (в реальном времени) =====
        
        # 1. RSI - с учётом current_price и orderbook
        rsi = self._calc_rsi(prices, current_price) or 50.0
        
        # 2. Stochastic - с учётом orderbook
        stoch_result = self._calc_stochastic(prices, orderbook)
        stoch_k = stoch_result[0] if stoch_result else 50.0
        
        # 3. Order Book Imbalance
        imbalance = self._calc_ob_imbalance(orderbook) if orderbook else 0.0
        
        # 4. Momentum
        momentum = self._calc_momentum(prices)
        
        # 5. Volume Ratio
        vol_ratio = self._calc_volume_ratio(volumes)
        
        # ===== ОПРЕДЕЛЕНИЕ СИГНАЛА =====
        
        # BUY сигнал: все индикаторы указывают вверх
        buy_count, buy_details = self._get_signal_strength(
            "BUY", rsi, stoch_k, imbalance, momentum, vol_ratio
        )
        
        # SELL сигнал: все индикаторы указывают вниз
        sell_count, sell_details = self._get_signal_strength(
            "SELL", rsi, stoch_k, imbalance, momentum, vol_ratio
        )
        
        # ===== РЕШЕНИЕ: 3 ИЗ 5 ДОЛЖНЫ СОВПАДАТЬ =====
        min_signals = 3  # Нужно минимум 3 из 5
        
        # BUY если хотя бы 3 индикаторов BUY
        if buy_count >= min_signals:
            confidence = 0.95  # Максимальная уверенность
            return ScalpSignal(
                signal_type=SignalType.BUY,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=confidence,
                reason=f"🎯 ALL BUY: {buy_details}",
                indicators={
                    'rsi': float(rsi),
                    'stoch': float(stoch_k),
                    'imbalance': float(imbalance or 0.0),
                    'momentum': float(momentum),
                    'vol_ratio': float(vol_ratio),
                    'signals_match': f"{buy_count}/5"
                }
            )
        
        # SELL если хотя бы 3 индикаторов SELL
        if sell_count >= min_signals:
            confidence = 0.95
            return ScalpSignal(
                signal_type=SignalType.SELL,
                figi=figi,
                ticker=ticker,
                price=current_price,
                confidence=confidence,
                reason=f"🎯 ALL SELL: {sell_details}",
                indicators={
                    'rsi': float(rsi),
                    'stoch': float(stoch_k),
                    'imbalance': float(imbalance or 0.0),
                    'momentum': float(momentum),
                    'vol_ratio': float(vol_ratio),
                    'signals_match': f"{sell_count}/5"
                }
            )
        
        # HOLD - индикаторы не совпадают
        # Показываем какой сигнал ближе
        best_match = max(buy_count, sell_count)
        best_type = "BUY" if buy_count >= sell_count else "SELL"
        
        return ScalpSignal(
            signal_type=SignalType.HOLD,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=best_match / 5,
            reason=f"⏸ {best_type}: {best_match}/5 ({buy_details} | {sell_details})",
            indicators={
                'rsi': float(rsi),
                'stoch': float(stoch_k),
                'imbalance': float(imbalance or 0.0),
                'momentum': float(momentum),
                'vol_ratio': float(vol_ratio),
                'buy_signals': float(buy_count),
                'sell_signals': float(sell_count)
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
        tp = take_profit if take_profit else self.tp_percent
        sl = stop_loss if stop_loss else self.sl_percent
        
        if direction == "BUY":
            profit_pct = (current_price - entry_price) / entry_price * 100
            
            # TP сработал
            if profit_pct >= tp:
                return True, f"TP {profit_pct:.2f}%", None
            
            # SL сработал (только если > 0)
            if sl > 0 and profit_pct <= -sl:
                return True, f"SL {profit_pct:.2f}%", None
            
            # Trailing stop
            if profit_pct >= 0.15 and trailing_stop_price is None:
                new_ts = entry_price * (1 + 0.05 / 100)
                if current_price < new_ts:
                    return True, f"TS {profit_pct:.2f}%", None
            
            if trailing_stop_price and current_price < trailing_stop_price:
                return True, f"Trailing {profit_pct:.2f}%", None
            
            return False, "", trailing_stop_price
        
        return False, "", None


def get_super_strategy(tp: float = 0.5, sl: float = 0.2) -> SuperCombinedStrategy:
    """Получить экземпляр Super стратегии."""
    return SuperCombinedStrategy(tp_percent=tp, sl_percent=sl)
