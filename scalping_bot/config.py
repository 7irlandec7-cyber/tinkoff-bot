"""
Scalping Bot Configuration
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


def _parse_manual_prices(env_str: str) -> dict:
    """Parse manual entry prices from env string like 'ALRS=19.59;VKCO=136.0'"""
    result = {}
    if not env_str:
        return result
    for pair in env_str.split(';'):
        pair = pair.strip()
        if '=' in pair:
            ticker, price_str = pair.split('=', 1)
            try:
                result[ticker.strip().upper()] = float(price_str.strip())
            except ValueError:
                pass
    return result


# Load .env if not already loaded
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass


@dataclass
class ScalpingSettings:
    """Scalping bot settings."""
    
    # Account
    tinkoff_token: str = ""
    tinkoff_account_id: Optional[str] = None
    
    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""  # Your Telegram chat ID for notifications
    
    # Trading limits
    initial_balance: float = 500.0  # Начальный баланс для расчёта %
    max_position_size: float = 100.0  # Макс. размер позиции в рублях
    use_full_balance: bool = True  # Использовать весь баланс при 100% сигнале
    max_positions: int = 3  # Макс. одновременных позиций (для мульти-режима)
    
    # Margin trading
    allow_margin: bool = True  # Разрешить маржинальную торговлю
    margin_multiplier: float = 2.0  # Множитель плеча (x2)
    margin_confidence_threshold: float = 0.85  # Порог уверенности для маржи (85%+)
    allow_short: bool = True  # Разрешить шорты при высокой уверенности
    manual_entry_prices: dict = field(default_factory=dict)  # Ручные цены входа: {'ALRS': 19.59, 'VKCO': 136.0}
    
    # Risk management
    stop_loss_percent: float = 0.5  # Стоп-лосс %
    take_profit_percent: float = 0.8  # Тейк-профит % (учитывай комиссию 0.1% round-trip)
    max_daily_loss_percent: float = 2.0  # Макс. дневной убыток %
    max_trades_per_day: int = 999  # Макс. сделок в день (999 = без лимита)
    commission_percent: float = 0.05  # Комиссия за сделку %

    # Среднесрок: лимиты удержания позиции
    min_hold_minutes: int = 30  # Не закрывать по TP раньше (защита от шума)
    max_hold_minutes: int = 240  # Принудительное закрытие после (не переносить через ночь)
    
    # Strategy
    strategy_name: str = "advanced"  # Стратегия: momentum, rsi_ema, orderbook, advanced
    pair_trading: bool = False  # Включить парный трейдинг
    timeframes: str = "5min"  # Таймфрейм для анализа
    min_volume: int = 1000  # Мин. объём для входа
    rsi_oversold: float = 30.0  # RSI для покупки
    rsi_overbought: float = 70.0  # RSI для продажи
    
    # Timing
    check_interval: int = 10  # Секунды между проверками (10 = часто, 30 = нормально)
    
    # Время торговли
    trading_hours_start: str = "10:00"
    trading_hours_end: str = "18:40"
    allow_non_trading_hours: bool = True  # Разрешить торговлю во внебиржевое время
    
    # Динамический TP/SL
    use_dynamic_tp: bool = True  # Динамический тейк-профит
    tp_low: float = 0.4  # Минимальный TP при низкой волатильности
    tp_high: float = 1.5  # Максимальный TP при высокой волатильности
    sl_low: float = 0.5  # Минимальный SL
    sl_high: float = 2.0  # Максимальный SL
    
    # Фильтр времени дня
    use_time_filter: bool = False  # Фильтр по времени торговли (отключено для теста)
    best_hours_start: str = "10:00"  # Лучшее время для торговли (начало)
    best_hours_end: str = "17:30"  # Лучшее время для торговли (конец)
    trading_hours_start: str = "10:00"  # Начало торговли
    trading_hours_end: str = "18:40"  # Конец торговли (до закрытия)
    allow_non_trading_hours: bool = True  # Разрешить торговлю во внебиржевое время
    
    # Notifications
    notify_trades: bool = True
    notify_signals: bool = True
    notify_errors: bool = True
    
    # Trading mode
    dry_run: bool = False  # True = только симуляция, False = реальные сделки
    
    @property
    def max_daily_loss_rub(self) -> float:
        """Макс. убыток в рублях."""
        return self.initial_balance * (self.max_daily_loss_percent / 100)
    
    @property
    def max_trade_loss_rub(self) -> float:
        """Макс. убыток на сделку."""
        return self.max_position_size * (self.stop_loss_percent / 100)
    
    @property
    def effective_take_profit(self) -> float:
        """Эффективный тейк-профит с учётом комиссии."""
        # Комиссия round-trip = 2 * commission (покупка + продажа)
        return self.take_profit_percent - (2 * self.commission_percent)
    
    @property
    def effective_stop_loss(self) -> float:
        """Эффективный стоп-лосс с учётом комиссии."""
        return self.stop_loss_percent + (2 * self.commission_percent)


def get_scalping_settings() -> ScalpingSettings:
    """Load settings from environment."""
    return ScalpingSettings(
        tinkoff_token=os.getenv("TINKOFF_TOKEN", ""),
        tinkoff_account_id=os.getenv("TINKOFF_ACCOUNT_ID"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        initial_balance=float(os.getenv("SCALPING_INITIAL_BALANCE", "500")),
        max_position_size=float(os.getenv("SCALPING_MAX_POSITION", "100")),
        use_full_balance=os.getenv("SCALPING_USE_FULL_BALANCE", "true").lower() == "true",
        max_positions=int(os.getenv("SCALPING_MAX_POSITIONS", "1")),
        allow_margin=os.getenv("SCALPING_ALLOW_MARGIN", "true").lower() == "true",
        margin_multiplier=float(os.getenv("SCALPING_MARGIN_MULTIPLIER", "1.0")),
        margin_confidence_threshold=float(os.getenv("SCALPING_MARGIN_CONFIDENCE", "0.90")),
        allow_short=os.getenv("SCALPING_ALLOW_SHORT", "true").lower() == "true",
        # Ручные цены входа: "ALRS=19.59;VKCO=136.0"
        manual_entry_prices=_parse_manual_prices(os.getenv("SCALPING_MANUAL_ENTRY_PRICES", "")),
        dry_run=os.getenv("SCALPING_DRY_RUN", "false").lower() == "true",
        stop_loss_percent=float(os.getenv("SCALPING_STOP_LOSS", "0.5")),
        take_profit_percent=float(os.getenv("SCALPING_TAKE_PROFIT", "0.8")),
        max_daily_loss_percent=float(os.getenv("SCALPING_MAX_DAILY_LOSS", "2.0")),
        max_trades_per_day=int(os.getenv("SCALPING_MAX_TRADES", "999")),
        min_hold_minutes=int(os.getenv("SCALPING_MIN_HOLD_MINUTES", "30")),
        max_hold_minutes=int(os.getenv("SCALPING_MAX_HOLD_MINUTES", "240")),
        strategy_name=os.getenv("SCALPING_STRATEGY", "advanced"),
        pair_trading=os.getenv("SCALPING_PAIR_TRADING", "false").lower() == "true",
        min_volume=int(os.getenv("SCALPING_MIN_VOLUME", "1000")),
        allow_non_trading_hours=os.getenv("SCALPING_ALLOW_NON_TRADING_HOURS", "true").lower() == "true",
        commission_percent=float(os.getenv("SCALPING_COMMISSION", "0.05")),
        check_interval=int(os.getenv("SCALPING_CHECK_INTERVAL", "10")),
    )
