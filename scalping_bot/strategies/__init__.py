"""
Scalping Strategies
"""
from .scalping_strategy import ScalpingStrategy, ScalpSignal, get_strategy
from .reliable_strategy import ReliableScalpingStrategy
from .profit_strategy import ProfitStrategy, get_profit_strategy
from .safe_scalping import SafeScalpingStrategy, SafeScalpingSettings
from .improved_scalping import ImprovedScalpingStrategy, ImprovedScalpingSettings

__all__ = ["ScalpingStrategy", "ScalpSignal", "get_strategy", "ReliableScalpingStrategy", "ProfitStrategy", "get_profit_strategy", "SafeScalpingStrategy", "SafeScalpingSettings", "ImprovedScalpingStrategy", "ImprovedScalpingSettings"]
