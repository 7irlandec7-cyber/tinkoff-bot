"""
Scalping Bot for Tinkoff Invest
"""
from .bot import ScalpingBot
from .config import get_scalping_settings

__all__ = ["ScalpingBot", "get_scalping_settings"]
