"""
Auto-Reinvestment Module - Автоматический реинвест прибыли
"""
import logging
from dataclasses import dataclass
from typing import Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class ReinvestConfig:
    """Конфигурация автореинвеста."""
    # Пороги прибыли и множители
    thresholds: Optional[Dict[float, float]] = None  # profit_percent -> multiplier
    
    # Автоматическое увеличение депозита
    auto_increase: bool = True
    min_profit_to_increase: float = 5.0  # Минимум +5% для увеличения
    
    # Максимумы
    max_balance_multiplier: float = 5.0  # Не увеличивать больше чем x5 от начального
    
    def __post_init__(self):
        if self.thresholds is None:
            # Прибыль -> множитель размера позиции
            self.thresholds = {
                5.0: 1.2,    # +5% → +20% к депозиту
                10.0: 1.5,   # +10% → +50% к депозиту
                20.0: 2.0,   # +20% → x2 депозит
                30.0: 2.5,   # +30% → x2.5 депозит
                50.0: 3.0,   # +50% → x3 депозит
            }


@dataclass
class BalanceHistory:
    """История баланса."""
    initial_balance: float
    current_balance: float
    peak_balance: float
    last_increase_time: datetime
    last_increase_percent: float
    
    def get_profit_percent(self) -> float:
        """Получить % прибыли от начального."""
        if self.initial_balance <= 0:
            return 0.0
        return (self.current_balance - self.initial_balance) / self.initial_balance * 100
    
    def get_peak_profit_percent(self) -> float:
        """Получить % прибыли от пика."""
        if self.peak_balance <= 0:
            return 0.0
        return (self.current_balance - self.peak_balance) / self.peak_balance * 100


class AutoReinvestor:
    """
    Автоматический реинвест прибыли.
    
    Логика:
    1. Отслеживаем баланс и прибыль
    2. При достижении порогов - увеличиваем размер позиции
    3. При просадке от пика - уменьшаем риск
    4. Динамический trailing stop
    """
    
    def __init__(self, config: Optional[ReinvestConfig] = None):
        self.config = config or ReinvestConfig()
        
        self.history: Optional[BalanceHistory] = None
        
        # Trailing metrics
        self.high_water_mark: float = 0.0  # Максимальный баланс
        self.drawdown_limit: float = 3.0   # Лимит просадки (3%)
        
        # Флаги
        self.rebalance_triggered: bool = False
        self.last_rebalance_reason: str = ""
        
        logger.info("📊 Auto-Reinvest модуль инициализирован")
    
    def initialize(self, initial_balance: float):
        """Инициализировать с начальным балансом."""
        self.history = BalanceHistory(
            initial_balance=initial_balance,
            current_balance=initial_balance,
            peak_balance=initial_balance,
            last_increase_time=datetime.now(),
            last_increase_percent=0.0
        )
        self.high_water_mark = initial_balance
        logger.info(f"   💰 Начальный баланс: {initial_balance:.2f}₽")
    
    def update_balance(self, new_balance: float) -> Dict:
        """
        Обновить баланс и вернуть рекомендации.
        
        Returns:
            dict с рекомендациями {should_adjust, multiplier, reason}
        """
        if not self.history:
            self.initialize(new_balance)
            return {"should_adjust": False, "multiplier": 1.0, "reason": "init"}
        
        old_balance = self.history.current_balance
        self.history.current_balance = new_balance
        
        # Обновляем peak
        if new_balance > self.history.peak_balance:
            self.history.peak_balance = new_balance
            self.high_water_mark = new_balance
        
        result = {
            "should_adjust": False,
            "multiplier": 1.0,
            "reason": "",
            "profit_percent": self.history.get_profit_percent(),
            "drawdown_percent": 0.0
        }
        
        # Просадка от пика
        drawdown = self.history.get_peak_profit_percent()
        result["drawdown_percent"] = drawdown
        
        # Если просадка слишком большая - уменьшаем риск
        if drawdown < -self.drawdown_limit:
            # Уменьшаем размер в 2 раза
            result["should_adjust"] = True
            result["multiplier"] = 0.5
            result["reason"] = f"Просадка {drawdown:.1f}% от пика - уменьшаем риск"
            logger.warning(f"⚠️ {result['reason']}")
            self.rebalance_triggered = True
            self.last_rebalance_reason = result["reason"]
            return result
        
        # Проверяем пороги прибыли
        profit = self.history.get_profit_percent()
        
        # Находим максимальный достигнутый порог
        current_multiplier = 1.0
        thresholds = self.config.thresholds or {}
        for threshold, multiplier in sorted(thresholds.items()):
            if profit >= threshold:
                current_multiplier = multiplier
        
        # Увеличиваем только если недавно не увеличивали
        if current_multiplier > 1.0:
            time_since_increase = (datetime.now() - self.history.last_increase_time).total_seconds()
            
            # Минимум 1 час между увеличениями
            if time_since_increase > 3600:
                result["should_adjust"] = True
                result["multiplier"] = current_multiplier
                result["reason"] = f"Прибыль {profit:.1f}% - увеличиваем депозит x{current_multiplier}"
                logger.info(f"✅ {result['reason']}")
                
                self.history.last_increase_time = datetime.now()
                self.history.last_increase_percent = (current_multiplier - 1) * 100
                self.rebalance_triggered = True
                self.last_rebalance_reason = result["reason"]
        
        return result
    
    def calculate_position_size(
        self,
        base_size: float,
        current_balance: float,
        risk_percent: float = 0.5
    ) -> float:
        """
        Рассчитать размер позиции с учётом реинвеста.
        
        Args:
            base_size: Базовый размер от настроек
            current_balance: Текущий баланс
            risk_percent: % риска на сделку (по умолчанию 0.5%)
        
        Returns:
            Рекомендуемый размер позиции
        """
        if not self.history:
            return base_size
        
        # Если достигнут максимальный множитель
        max_multiplier = self.config.max_balance_multiplier
        
        # Текущий множитель относительно начального
        current_mult = current_balance / self.history.initial_balance
        
        if current_mult > max_multiplier:
            current_mult = max_multiplier
        
        # Размер = базовый × множитель
        size = base_size * current_mult
        
        # Но не больше чем risk_percent от баланса
        max_by_risk = current_balance * (risk_percent / 100)
        
        return min(size, max_by_risk)
    
    def get_trailing_stop_multiplier(self, profit_percent: float) -> float:
        """
        Получить множитель для trailing stop на основе прибыли.
        
        Больше прибыль - больше защита (trailing ближе к цене).
        """
        if profit_percent < 0.5:
            return 1.0  # Стандартный
        
        if profit_percent < 1.0:
            return 1.2  # +20% к trailing
        
        if profit_percent < 2.0:
            return 1.5  # +50% к trailing
        
        if profit_percent < 3.0:
            return 2.0  # x2 trailing
        
        return 2.5  # Максимальная защита
    
    def get_status(self) -> str:
        """Получить статус реинвеста."""
        if not self.history:
            return "Не инициализирован"
        
        profit = self.history.get_profit_percent()
        drawdown = self.history.get_peak_profit_percent()
        
        lines = [
            f"💰 Баланс: {self.history.current_balance:.2f}₽",
            f"📈 Прибыль: {profit:+.2f}%",
            f"🏔️ Пик: {self.history.peak_balance:.2f}₽",
            f"📉 Просадка от пика: {drawdown:.2f}%",
        ]
        
        if self.rebalance_triggered:
            lines.append(f"⚡ {self.last_rebalance_reason}")
        
        return "\n".join(lines)


def get_auto_reinvestor(config: Optional[ReinvestConfig] = None) -> AutoReinvestor:
    """Получить экземпляр автореинвестора."""
    return AutoReinvestor(config or ReinvestConfig())
