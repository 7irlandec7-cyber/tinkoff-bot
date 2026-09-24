"""
Pair Trading Strategy - Парный трейдинг
"""
import logging
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from collections import deque
import statistics

from .scalping_strategy import SignalType, ScalpSignal

logger = logging.getLogger(__name__)


@dataclass
class Pair:
    """Торговая пара."""
    long_ticker: str
    long_figi: str
    short_ticker: str
    short_figi: str
    name: str
    sector: str
    spread_history: deque = None
    last_spread: float = 0.0
    z_score: float = 0.0
    
    def __post_init__(self):
        if self.spread_history is None:
            self.spread_history = deque(maxlen=50)


class PairTradingStrategy:
    """
    Стратегия парного трейдинга.
    
    Логика:
    - Когда спред между парой расширяется/сужается - одна акция недооценена/переоценена
    - LONG отстающая акция, SHORT лидирующая
    - Когда спред возвращается к среднему - закрываем обе позы
    """
    
    def __init__(
        self,
        lookback_period: int = 20,
        entry_threshold: float = 2.0,  # Z-score для входа
        exit_threshold: float = 0.5,   # Z-score для выхода
        max_pairs: int = 5,
        correlation_min: float = 0.6,  # Минимальная корреляция пары
    ):
        self.lookback_period = lookback_period
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.max_pairs = max_pairs
        self.correlation_min = correlation_min
        
        # Активные пары
        self.pairs: Dict[str, Pair] = {}
        
        # Цены для расчёта спреда
        self.prices: Dict[str, float] = {}
        self.price_history: Dict[str, deque] = {}
        
        # Открытые позиции по парам
        self.open_pair_positions: Dict[str, dict] = {}  # pair_name -> {long/short, entry_spread}
        
        logger.info(
            f"📊 Pair Trading: lookback={lookback_period}, "
            f"entry_z={entry_threshold}, exit_z={exit_threshold}"
        )
    
    def add_pair(self, long_ticker: str, long_figi: str, 
                  short_ticker: str, short_figi: str,
                  name: str = "", sector: str = ""):
        """Добавить пару для мониторинга."""
        pair_id = f"{long_ticker}_{short_ticker}"
        self.pairs[pair_id] = Pair(
            long_ticker=long_ticker,
            long_figi=long_figi,
            short_ticker=short_ticker,
            short_figi=short_figi,
            name=name or f"{long_ticker}/{short_ticker}",
            sector=sector
        )
        logger.info(f"   📈 Пара добавлена: {name or pair_id}")
    
    def update_prices(self, figi: str, ticker: str, price: float):
        """Обновить цену инструмента."""
        self.prices[ticker] = price
        
        if ticker not in self.price_history:
            self.price_history[ticker] = deque(maxlen=100)
        self.price_history[ticker].append(price)
    
    def calculate_spread(self, pair: Pair) -> Optional[float]:
        """Рассчитать спред пары (normalized)."""
        long_price = self.prices.get(pair.long_ticker)
        short_price = self.prices.get(pair.short_ticker)
        
        if not long_price or not short_price:
            return None
        
        # Спред = цена длинной / цена короткой
        # Или можно использовать разницу нормализованных цен
        try:
            # Нормализуем цены к начальным
            long_hist = list(self.price_history.get(pair.long_ticker, [long_price]))
            short_hist = list(self.price_history.get(pair.short_ticker, [short_price]))
            
            if len(long_hist) < 5 or len(short_hist) < 5:
                return None
            
            # Доходность за период
            long_ret = (long_price - long_hist[0]) / long_hist[0] if long_hist[0] > 0 else 0
            short_ret = (short_price - short_hist[0]) / short_hist[0] if short_hist[0] > 0 else 0
            
            # Спред = разница доходностей
            spread = long_ret - short_ret
            
            return spread * 100  # В процентах
            
        except Exception as e:
            logger.debug(f"Ошибка расчёта спреда: {e}")
            return None
    
    def calculate_z_score(self, pair: Pair) -> Optional[float]:
        """Рассчитать Z-score спреда."""
        if len(pair.spread_history) < self.lookback_period:
            return None
        
        spreads = list(pair.spread_history)[-self.lookback_period:]
        mean = statistics.mean(spreads)
        std = statistics.stdev(spreads) if len(spreads) > 1 else 0.001
        
        if std == 0:
            return None
        
        z = (pair.last_spread - mean) / std
        return z
    
    def check_correlation(self, pair: Pair) -> float:
        """Проверить корреляцию пары."""
        long_hist = list(self.price_history.get(pair.long_ticker, []))
        short_hist = list(self.price_history.get(pair.short_ticker, []))
        
        if len(long_hist) < 10 or len(short_hist) < 10:
            return 0.0
        
        # Простая корреляция
        n = min(len(long_hist), len(short_hist), 20)
        
        changes_long = []
        changes_short = []
        
        for i in range(n):
            idx = -n + i
            if idx > 0:
                cl = (long_hist[idx] - long_hist[idx-1]) / long_hist[idx-1] * 100
                cs = (short_hist[idx] - short_hist[idx-1]) / short_hist[idx-1] * 100
                changes_long.append(cl)
                changes_short.append(cs)
        
        if not changes_long or not changes_short:
            return 0.0
        
        # Корреляция Пирсона
        mean_l = sum(changes_long) / len(changes_long)
        mean_s = sum(changes_short) / len(changes_short)
        
        numerator = sum((l - mean_l) * (s - mean_s) for l, s in zip(changes_long, changes_short))
        denom_l = sum((l - mean_l) ** 2 for l in changes_long) ** 0.5
        denom_s = sum((s - mean_s) ** 2 for s in changes_short) ** 0.5
        
        if denom_l * denom_s == 0:
            return 0.0
        
        return numerator / (denom_l * denom_s)
    
    def analyze_pair(self, pair_id: str) -> List[ScalpSignal]:
        """Анализировать пару и вернуть сигналы."""
        pair = self.pairs.get(pair_id)
        if not pair:
            return []
        
        signals = []
        
        # Проверяем корреляцию
        corr = self.check_correlation(pair)
        if corr < self.correlation_min:
            return []  # Пара недостаточно коррелирована
        
        # Проверяем, есть ли уже открытая позиция по этой паре
        has_position = pair_id in self.open_pair_positions
        
        if not has_position and len(self.open_pair_positions) >= self.max_pairs:
            return []  # Достигнут лимит пар
        
        # Рассчитываем спред и Z-score
        spread = self.calculate_spread(pair)
        if spread is None:
            return []
        
        pair.last_spread = spread
        pair.spread_history.append(spread)
        
        z_score = self.calculate_z_score(pair)
        if z_score is None:
            return []
        
        pair.z_score = z_score
        
        # Сигналы
        long_price = self.prices.get(pair.long_ticker, 0)
        short_price = self.prices.get(pair.short_ticker, 0)
        
        if not has_position:
            # Проверяем вход
            # Z > 2: спред слишком высокий, шортим спред (long short, short long)
            if z_score > self.entry_threshold:
                signals.append(ScalpSignal(
                    signal_type=SignalType.BUY,
                    figi=pair.long_figi,
                    ticker=pair.long_ticker,
                    price=long_price,
                    confidence=min(abs(z_score) / 3.0, 0.95),
                    reason=f"Pair {pair.name}: Z={z_score:.1f} - LONG spread",
                    indicators={"pair": pair_id, "z_score": z_score, "action": "long_spread"}
                ))
                
                signals.append(ScalpSignal(
                    signal_type=SignalType.SELL,
                    figi=pair.short_figi,
                    ticker=pair.short_ticker,
                    price=short_price,
                    confidence=min(abs(z_score) / 3.0, 0.95),
                    reason=f"Pair {pair.name}: Z={z_score:.1f} - SHORT spread",
                    indicators={"pair": pair_id, "z_score": z_score, "action": "short_spread"}
                ))
            
            # Z < -2: спред слишком низкий, покупаем спред (long long, short short)
            elif z_score < -self.entry_threshold:
                signals.append(ScalpSignal(
                    signal_type=SignalType.BUY,
                    figi=pair.long_figi,
                    ticker=pair.long_ticker,
                    price=long_price,
                    confidence=min(abs(z_score) / 3.0, 0.95),
                    reason=f"Pair {pair.name}: Z={z_score:.1f} - LONG spread",
                    indicators={"pair": pair_id, "z_score": z_score, "action": "long_spread"}
                ))
        
        else:
            # Проверяем выход
            pos = self.open_pair_positions[pair_id]
            if abs(z_score) < self.exit_threshold:
                # Закрываем позицию
                signals.append(ScalpSignal(
                    signal_type=SignalType.CLOSE_LONG if pos.get("long_first") else SignalType.CLOSE_SHORT,
                    figi=pair.long_figi,
                    ticker=pair.long_ticker,
                    price=long_price,
                    confidence=0.9,
                    reason=f"Pair {pair.name}: Z={z_score:.1f} - Close spread",
                    indicators={"pair": pair_id, "z_score": z_score, "action": "close"}
                ))
        
        return signals
    
    def analyze_all(self) -> List[ScalpSignal]:
        """Анализировать все пары."""
        signals = []
        for pair_id in self.pairs:
            signals.extend(self.analyze_pair(pair_id))
        return signals
    
    def analyze(self, figi: str, ticker: str, current_price: float, volume: float = 0, orderbook=None) -> ScalpSignal:
        """Анализ для совместимости с ботом."""
        # Обновляем цены
        self.update_prices(figi, ticker, current_price)
        
        # Ищем пару с этим тикером
        for pair_id, pair in self.pairs.items():
            if pair.long_figi == figi or pair.short_figi == figi:
                signals = self.analyze_pair(pair_id)
                if signals:
                    return signals[0]  # Возвращаем первый сигнал
        
        # Нет сигнала
        from .scalping_strategy import SignalType
        return ScalpSignal(
            signal_type=SignalType.HOLD,
            figi=figi,
            ticker=ticker,
            price=current_price,
            confidence=0.0,
            reason="Pair trading: waiting for pair signal",
            indicators={}
        )
    
    def open_pair_position(self, pair_id: str, long_first: bool = True):
        """Записать открытие позиции по паре."""
        pair = self.pairs.get(pair_id)
        if pair:
            self.open_pair_positions[pair_id] = {
                "entry_spread": pair.last_spread,
                "entry_z": pair.z_score,
                "long_first": long_first,
                "entry_time": None
            }
    
    def close_pair_position(self, pair_id: str):
        """Закрыть позицию по паре."""
        if pair_id in self.open_pair_positions:
            del self.open_pair_positions[pair_id]
            logger.info(f"   ✅ Пара {pair_id} закрыта")
    
    def should_close_position(
        self,
        figi: str,
        entry_price: float,
        current_price: float,
        direction: str,
        take_profit: float = 0.8,
        stop_loss: float = 1.0
    ) -> Tuple[bool, str]:
        """Стандартная проверка для обратной совместимости."""
        return False, ""  # Парный трейдинг использует свой exit


def get_pair_trading_strategy() -> PairTradingStrategy:
    """Получить экземпляр стратегии парного трейдинга."""
    return PairTradingStrategy(
        lookback_period=20,
        entry_threshold=2.0,
        exit_threshold=0.5,
        max_pairs=3,
        correlation_min=0.5,
    )
