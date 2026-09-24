"""
Scalping Trader - Module for executing scalping trades
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime, time
from enum import Enum

from scalping_bot.positions_storage import save_positions, load_positions

logger = logging.getLogger(__name__)


class PositionStatus(Enum):
    """Статус позиции."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    STOPPED = "STOPPED"


@dataclass
class Position:
    """Открытая позиция."""
    figi: str
    ticker: str
    direction: str  # "BUY" or "SELL"
    entry_price: float
    quantity: int
    entry_time: datetime
    entry_reason: str
    status: PositionStatus = PositionStatus.OPEN
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None
    pnl_percent: Optional[float] = None
    
    # Trailing stop
    trailing_stop_active: bool = False
    trailing_stop_price: float = 0.0
    trailing_stop_high: float = 0.0
    
    # Защита от двойного закрытия
    is_closing: bool = False

    # Биржевой SL-ордер (страховка)
    exchange_sl_order_id: Optional[str] = None
    exchange_sl_price: Optional[float] = None

    # Биржевой TP-ордер (для отображения в терминале)
    exchange_tp_order_id: Optional[str] = None
    exchange_tp_price: Optional[float] = None

    def update_pnl(self, current_price: float):
        """Обновить PnL позиции."""
        if self.direction == "BUY":
            self.pnl = (current_price - self.entry_price) * self.quantity
            self.pnl_percent = (current_price - self.entry_price) / self.entry_price * 100
        else:
            self.pnl = (self.entry_price - current_price) * self.quantity
            self.pnl_percent = (self.entry_price - current_price) / self.entry_price * 100
    
    def close(self, exit_price: float, reason: str, commission_percent: float = 0.05):
        """Закрыть позицию с учётом комиссии.
        
        Примечание: Комиссия за ПОКУПКУ уже взимается брокером при открытии.
        При закрытии платим только комиссию за ПРОДАЖУ.
        """
        self.exit_price = exit_price
        self.exit_time = datetime.now()
        self.status = PositionStatus.CLOSED
        
        # Расчёт PnL до комиссии
        if self.direction == "BUY":
            gross_pnl = (exit_price - self.entry_price) * self.quantity
        else:
            gross_pnl = (self.entry_price - exit_price) * self.quantity
        
        # Комиссия ТОЛЬКО за продажу (за покупку уже заплатили)
        exit_value = exit_price * self.quantity
        commission = exit_value * (commission_percent / 100)
        
        # PnL за вычётом комиссии
        self.pnl = gross_pnl - commission
        self.pnl_percent = self.pnl / (self.entry_price * self.quantity) * 100 if self.entry_price > 0 else 0
        self.entry_reason = reason
    
    def __str__(self):
        emoji = "🟢" if self.direction == "BUY" else "🔴"
        pnl_str = f"{self.pnl:+.2f}₽ ({self.pnl_percent:+.2f}%)" if self.pnl is not None else "—"
        return f"{emoji} {self.ticker}: {self.direction} {self.quantity}@₽{self.entry_price:.2f} | PnL: {pnl_str}"


@dataclass
class TradeStats:
    """Статистика торговли за день."""
    date: str
    trades_count: int = 0
    successful_trades: int = 0
    failed_trades: int = 0
    total_pnl: float = 0.0
    max_daily_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    positions: List[Position] = field(default_factory=list)
    
    
    def add_trade(self, position: Position):
        """Добавить закрытую позицию."""
        self.positions.append(position)
        self.trades_count += 1
        
        if position.pnl:
            self.total_pnl += position.pnl
            
            if position.pnl > 0:
                self.successful_trades += 1
                self.largest_win = max(self.largest_win, position.pnl)
            else:
                self.failed_trades += 1
                self.largest_loss = min(self.largest_loss, position.pnl)
            
            self.max_daily_loss = min(self.max_daily_loss, self.total_pnl)
    
    def is_limit_reached(self, max_trades: int, max_loss_percent: float, initial_balance: float) -> bool:
        """Проверить, достигнут ли лимит."""
        if self.trades_count >= max_trades:
            return True
        if self.max_daily_loss < -initial_balance * max_loss_percent / 100:
            return True
        return False
    
    def get_summary(self) -> str:
        """Получить текстовую сводку."""
        win_rate = self.successful_trades / max(self.trades_count, 1) * 100
        return (
            f"📊 <b>Статистика дня</b>\n\n"
            f"📈 Сделок: {self.trades_count}\n"
            f"✅ Успешных: {self.successful_trades}\n"
            f"❌ Убыточных: {self.failed_trades}\n"
            f"📊 Win Rate: {win_rate:.0f}%\n\n"
            f"💰 PnL: {self.total_pnl:+.2f}₽\n"
            f"📉 Макс. просадка: {self.max_daily_loss:.2f}₽\n"
            f"🏆 Лучшая сделка: {self.largest_win:.2f}₽\n"
            f"💔 Худшая сделка: {self.largest_loss:.2f}₽"
        )


class ScalpingTrader:
    """
    Трейдер для скальпинга с поддержкой МУЛЬТИ-ПОЗИЦИЙ.
    
    Управляет открытием/закрытием позиций, стоп-лоссами и тейк-профитами.
    """
    
    def __init__(
        self,
        client,
        settings,
        strategy,
        telegram_notifier=None
    ):
        self.client = client
        self.settings = settings
        self.strategy = strategy
        self.telegram = telegram_notifier
        
        # МУЛЬТИ-ПОЗИЦИИ: список открытых позиций
        self.positions: List[Position] = []
        
        # Свойство для обратной совместимости (первая позиция)
        @property
        def current_position(self) -> Optional[Position]:
            return self.positions[0] if self.positions else None
        
        self.stats: Optional[TradeStats] = None
        
        # Загрузить открытые позиции из API
        self._load_open_positions()
        
        # Сброс статистики на новый день
        self._reset_daily_stats()
    
    def get_portfolio_value(self) -> float:
        """
        Получить общую стоимость портфеля (деньги + бумаги).
        """
        try:
            api_positions = self.client.get_positions()
            
            # Денежный баланс
            total = 0.0
            for m in api_positions.get('money', []):
                units = int(m.get('units', 0))
                nano = int(m.get('nano', 0))
                total += units + nano / 1e9
            
            # Стоимость бумаг
            for s in api_positions.get('securities', []):
                balance = int(s.get('balance', 0))
                if balance > 0:
                    figi = s.get('figi')
                    try:
                        ob = self.client.get_orderbook(figi, 1)
                        price = float(ob.get('lastPrice', {}).get('units', 0)) + float(ob.get('lastPrice', {}).get('nano', 0)) / 1e9
                        total += balance * price
                    except:
                        pass
            
            return total
        except Exception as e:
            logger.error(f"Ошибка получения стоимости портфеля: {e}")
            return self.settings.initial_balance  # Fallback
    
    def _load_open_positions(self):
        """Загрузить открытые позиции из API."""
        try:
            print("[TRADER] Загрузка открытых позиций...", flush=True)
            
            # Загружаем сохранённые позиции
            saved_positions = load_positions()
            print(f"[TRADER] Загружено {len(saved_positions)} сохранённых позиций", flush=True)
            
            # Получаем позиции из API
            api_positions = self.client.get_positions()
            print(f"[TRADER] API ответ: {api_positions}", flush=True)
            
            # Получаем текущие цены для всех инструментов
            figi_list = [sec.get('figi') for sec in api_positions.get('securities', []) if sec.get('figi')]
            current_prices = {}
            if figi_list:
                price_data = self.client.get_last_prices(figi_list)
                for item in price_data:
                    figi = item.get('figi', '')
                    units = item.get('price', {}).get('units', 0)
                    nano = item.get('price', {}).get('nano', 0)
                    current_prices[figi] = float(units) + float(nano) / 1e9
            
            positions_found = []
            
            # Ручные цены входа из конфигурации
            manual_entry_prices = getattr(self.settings, 'manual_entry_prices', {})
            
            if api_positions and api_positions.get('securities'):
                for sec in api_positions.get('securities', []):
                    balance = int(sec.get('balance', 0))
                    if balance != 0:
                        ticker = sec.get('ticker', 'UNKNOWN')
                        figi = sec.get('figi', '')
                        
                        # Приоритет: ручная цена > сохранённая цена > текущая цена
                        if ticker in manual_entry_prices:
                            entry_price = manual_entry_prices[ticker]
                            print(f"[TRADER] {ticker}: ручная цена входа {entry_price:.2f}₽", flush=True)
                        elif figi in saved_positions:
                            entry_price = saved_positions[figi]['entry_price']
                            entry_time_str = saved_positions[figi].get('entry_time', datetime.now().isoformat())
                            print(f"[TRADER] {ticker}: сохранённая цена входа {entry_price:.4f}₽", flush=True)
                        elif figi in current_prices:
                            entry_price = current_prices[figi]
                            print(f"[TRADER] {ticker}: текущая цена {entry_price:.4f}₽ (⚠️ НЕ СРЕДНЯЯ!)", flush=True)
                        else:
                            entry_price = 0.0
                            print(f"[TRADER] {ticker}: ⚠️ НЕТ ЦЕНЫ ВХОДА!", flush=True)
                        
                        print(f"[TRADER] Загружена позиция: {ticker} x{balance} @ {entry_price:.4f}₽ ({figi})", flush=True)
                        
                        position = Position(
                            figi=figi,
                            ticker=ticker,
                            direction="BUY" if balance > 0 else "SELL",
                            entry_price=entry_price,
                            quantity=self._shares_to_lots(figi, balance),
                            entry_time=datetime.now(),
                            entry_reason="Загружена из портфеля"
                        )
                        
                        # Восстанавливаем учёт биржевого SL, размещённого до рестарта
                        saved_rec = saved_positions.get(figi) or {}
                        restored_sl_id = saved_rec.get("exchange_sl_order_id")
                        restored_sl_px = saved_rec.get("exchange_sl_price")
                        if restored_sl_id:
                            position.exchange_sl_order_id = restored_sl_id
                            try:
                                position.exchange_sl_price = float(restored_sl_px) if restored_sl_px else None
                            except (TypeError, ValueError):
                                position.exchange_sl_price = None
                            print(
                                f"[TRADER] {ticker}: восстановлен биржевой SL {restored_sl_id} "
                                f"@ {position.exchange_sl_price}",
                                flush=True
                            )

                        restored_tp_id = saved_rec.get("exchange_tp_order_id")
                        restored_tp_px = saved_rec.get("exchange_tp_price")
                        if restored_tp_id:
                            position.exchange_tp_order_id = restored_tp_id
                            try:
                                position.exchange_tp_price = float(restored_tp_px) if restored_tp_px else None
                            except (TypeError, ValueError):
                                position.exchange_tp_price = None
                            print(
                                f"[TRADER] {ticker}: восстановлен биржевой TP {restored_tp_id} "
                                f"@ {position.exchange_tp_price}",
                                flush=True
                            )

                        self.positions.append(position)
                        positions_found.append(ticker)
                        print(f"[TRADER] Активная позиция: {position.ticker} @ {position.entry_price:.2f}₽", flush=True)
            
            print(f"[TRADER] Всего открытых позиций: {len(self.positions)}", flush=True)
            if positions_found:
                print(f"[TRADER] Позиции: {', '.join(positions_found)}", flush=True)
            print("[TRADER] Открытые позиции загружены", flush=True)
            
            # НЕ сохраняем позиции после загрузки из брокера!
            # Сохранённые цены входа берутся из файла (который был создан при открытии позиций)
        except Exception as e:
            print(f"[TRADER] Ошибка загрузки позиций: {e}", flush=True)
    
    def _reset_daily_stats(self):
        """Сбросить статистику на новый день."""
        today = datetime.now().strftime("%Y-%m-%d")
        self.stats = TradeStats(date=today)
    
    def is_trading_hours(self) -> bool:
        """Проверить, торговый ли сейчас час (по Москве)."""
        # Если внебиржевая торговля разрешена - всегда возвращаем True
        if getattr(self.settings, 'allow_non_trading_hours', False):
            return True
        
        import zoneinfo
        try:
            moscow_tz = zoneinfo.ZoneInfo("Europe/Moscow")
            now = datetime.now(tz=moscow_tz).time()
        except:
            from datetime import timezone, timedelta
            moscow_tz = timezone(timedelta(hours=3))
            now = datetime.now(tz=moscow_tz).time()
        
        start = time(10, 0)
        end = time(18, 40)
        
        return start <= now <= end
    
    def can_open_position(self) -> bool:
        """Можно ли открыть новую позицию."""
        # Проверяем лимит на количество одновременных позиций
        max_positions = getattr(self.settings, 'max_positions', 3)
        if len(self.positions) >= max_positions:
            logger.warning("Лимит позиций достигнут")
            return False
        
        # Проверить лимиты статистики (используем начальный депозит для расчёта лимита)
        if self.stats and self.stats.is_limit_reached(
            self.settings.max_trades_per_day,
            self.settings.max_daily_loss_percent,
            self.settings.initial_balance
        ):
            logger.warning("Лимиты статистики достигнуты")
            return False
        
        # Проверить торговые часы
        if not self.is_trading_hours():
            logger.warning("Не торговые часы")
            return False
        
        # Проверить достаточно ли средств для мин. позиции
        min_position_value = 100  # Минимум 100₽
        try:
            # Используем get_positions для надёжности
            positions_data = self.client.get_positions()
            
            # Получаем денежный баланс
            cash_balance = 0.0
            if positions_data and positions_data.get('money'):
                for m in positions_data.get('money', []):
                    units = int(m.get('units', 0))
                    nano = int(m.get('nano', 0))
                    cash_balance += units + nano / 1e9
            
            # Получаем стоимость бумаг (для расчёта общего баланса)
            securities_value = 0.0
            for s in positions_data.get('securities', []):
                balance = int(s.get('balance', 0))
                if balance > 0:
                    figi = s.get('figi')
                    try:
                        ob = self.client.get_orderbook(figi, 1)
                        price = float(ob.get('lastPrice', {}).get('units', 0)) + float(ob.get('lastPrice', {}).get('nano', 0)) / 1e9
                        securities_value += balance * price
                    except:
                        pass  # Пропускаем ошибки получения цены
            
            total_balance = cash_balance + securities_value
            logger.info(f"💰 Баланс: {total_balance:.2f}₽ (наличные: {cash_balance:.2f}₽, бумаги: {securities_value:.2f}₽)")
            
            # Блокируем если общий баланс < минимума
            if total_balance < min_position_value:
                logger.warning(f"⚠️ Недостаточно средств: {total_balance:.2f}₽ < {min_position_value}₽")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка проверки баланса: {e}")
            return False  # Блокируем открытие при ошибке
        
        return True
    
    def can_close_position(self) -> bool:
        """Можно ли закрыть позицию."""
        return len(self.positions) > 0
    
    async def check_and_manage_all_positions(self, prices: List[dict]) -> List[str]:
        """
        Проверить и управлять ВСЕМИ открытыми позициями.
        МГНОВЕННОЕ исполнение TP/SL.
        
        Args:
            prices: Список цен {figi, ticker, price}
        
        Returns:
            Список сообщений о действиях
        """
        results = []

        effective_tp = self.settings.take_profit_percent
        effective_sl = self.settings.stop_loss_percent

        # СИНХРОНИЗАЦИЯ ПОЗИЦИЙ С API - критически важно для работы TP/SL
        # Получаем реальные позиции из API и сопоставляем с self.positions
        try:
            api_positions = self.client.get_positions()
            api_securities = {s.get('figi'): s for s in api_positions.get('securities', []) if int(s.get('balance', 0)) != 0}
        except Exception as e:
            logger.error(f"Ошибка получения позиций из API: {e}")
            api_securities = {}

        # Обновляем self.positions на основе реальных данных API
        synced_positions = []
        manual_entry_prices = getattr(self.settings, 'manual_entry_prices', {})
        saved_positions = load_positions()

        for figi, sec in api_securities.items():
            balance = int(sec.get('balance', 0))
            ticker = sec.get('ticker', 'UNKNOWN')

            # Ищем существующую позицию в self.positions
            existing = None
            for p in self.positions:
                if p.figi == figi:
                    existing = p
                    break

            if existing:
                # Обновляем существующую (balance в АКЦИЯХ -> переводим в ЛОТЫ)
                existing.quantity = self._shares_to_lots(figi, balance)
                if balance > 0:
                    existing.direction = "BUY"
                else:
                    existing.direction = "SELL"
                synced_positions.append(existing)
            else:
                # Создаём новую позицию из API
                if ticker in manual_entry_prices:
                    entry_price = manual_entry_prices[ticker]
                elif figi in saved_positions:
                    entry_price = saved_positions[figi]['entry_price']
                else:
                    # Fallback - берём текущую цену (неточно, но лучше чем ничего)
                    try:
                        ob = self.client.get_orderbook(figi, 1)
                        lp = ob.get('lastPrice', {})
                        entry_price = float(lp.get('units', 0)) + float(lp.get('nano', 0)) / 1e9
                        logger.warning(f"⚠️ {ticker}: нет сохранённой цены входа, используется текущая {entry_price:.2f}₽")
                    except:
                        entry_price = 0.0

                position = Position(
                    figi=figi,
                    ticker=ticker,
                    direction="BUY" if balance > 0 else "SELL",
                    entry_price=entry_price,
                    quantity=self._shares_to_lots(figi, balance),
                    entry_time=datetime.now(),
                    entry_reason="Синхронизировано из API"
                )
                synced_positions.append(position)
                logger.info(
                    f"📥 Синхронизирована позиция: {ticker} {balance} акций = "
                    f"{synced_positions[-1].quantity} лотов @ {entry_price:.2f}₽"
                )

        # Удаляем позиции, которых больше нет в API
        for p in list(self.positions):
            if p not in synced_positions:
                logger.info(f"🗑️ Позиция {p.ticker} больше не в API, удаляем из списка")

        self.positions = synced_positions

        if api_securities:
            logger.info(f"📊 Активных позиций в API: {len(api_securities)} | Отслеживаем: {len(self.positions)}")
        else:
            logger.debug("📊 Нет открытых позиций в API")

        # Страховка: у каждой позиции ОБЯЗАН быть биржевой SL.
        # Лечит позиции, открытые до фикса, потерявшие ID при рестарте
        # и те, чей стоп биржа отклонила при открытии.
        try:
            self._ensure_exchange_sl()
            self._ensure_exchange_tp()
        except Exception as e:
            logger.warning(f"⚠️ Проверка биржевых SL не выполнена: {e}")

        # Получаем СВЕЖИЕ цены через GetOrderBook для каждой позиции
        # ИСПОЛЬЗУЕМ bid/ask для точности (lastPrice может быть устаревшим)
        fresh_prices = {}
        for position in self.positions:
            try:
                ob = self.client.get_orderbook(position.figi, depth=1)
                if ob:
                    price = None
                    # Для BUY позиции используем bid (цена продажи)
                    # Для SELL позиции используем ask (цена покупки)
                    if position.direction == "BUY":
                        # Закрываем BUY -> продаём по bid
                        bids = ob.get('bids', [])
                        if bids:
                            bid = bids[0].get('price', {})
                            units = bid.get('units', 0)
                            nano = bid.get('nano', 0)
                            price = float(units) + float(nano) / 1e9
                    else:
                        # Закрываем SELL -> покупаем по ask
                        asks = ob.get('asks', [])
                        if asks:
                            ask = asks[0].get('price', {})
                            units = ask.get('units', 0)
                            nano = ask.get('nano', 0)
                            price = float(units) + float(nano) / 1e9

                    # Fallback на lastPrice если bid/ask недоступны
                    if price is None:
                        last = ob.get('lastPrice', {})
                        if last:
                            units = last.get('units', 0)
                            nano = last.get('nano', 0)
                            price = float(units) + float(nano) / 1e9

                    if price is not None:
                        fresh_prices[position.figi] = price
            except Exception as e:
                logger.warning(f"Не удалось получить свежую цену для {position.ticker}: {e}")

        # Используем свежие цены или fallback на prices
        price_map = {p['figi']: p['price'] for p in prices}
        for figi, fresh_price in fresh_prices.items():
            price_map[figi] = fresh_price

        # DEBUG: проверяем какие цены используются
        if fresh_prices:
            logger.info(f"📊 Fresh prices получены: {len(fresh_prices)}, batch prices: {len(prices)}")
            for figi, fp in fresh_prices.items():
                batch_p = price_map.get(figi, 'N/A')
                logger.info(f"  {figi}: fresh={fp:.4f}, batch={batch_p:.4f}")

        positions_to_close = []
        for position in self.positions:
            current_price = price_map.get(position.figi)
            if current_price is None:
                # Нет цены — пропускаем
                logger.warning(f"⚠️ Нет цены для {position.ticker}, пропускаю проверку TP/SL")
                continue
            
            position.update_pnl(current_price)
            
            # Trailing stop
            if hasattr(self.strategy, 'create_trailing_stop'):
                if not position.trailing_stop_active:
                    position.trailing_stop_high = current_price
                    position.trailing_stop_price = position.entry_price * (1 - 0.5 / 100)
                    position.trailing_stop_active = True
                else:
                    if position.direction == "BUY":
                        if current_price > position.trailing_stop_high:
                            position.trailing_stop_high = current_price
                            position.trailing_stop_price = current_price * (1 - 0.3 / 100)
                        if current_price <= position.trailing_stop_price:
                            profit = (current_price - position.entry_price) / position.entry_price * 100
                            logger.info(f"🚨 TP/SL: {position.ticker} trailing stop сработал! Profit: {profit:.2f}%")
                            positions_to_close.append((position, current_price, f"🚨 Trailing Stop: {profit:.2f}%"))
                            continue
                    else:
                        if current_price < position.trailing_stop_high:
                            position.trailing_stop_high = current_price
                            position.trailing_stop_price = current_price * (1 + 0.3 / 100)
                        if current_price >= position.trailing_stop_price:
                            profit = (position.entry_price - current_price) / position.entry_price * 100
                            logger.info(f"🚨 TP/SL: {position.ticker} trailing stop сработал! Profit: {profit:.2f}%")
                            positions_to_close.append((position, current_price, f"🚨 Trailing Stop: {profit:.2f}%"))
                            continue
            
            # Проверяем TP/SL
            pnl_check = ((current_price - position.entry_price) / position.entry_price) * 100
            if position.direction == "SELL":
                pnl_check = -pnl_check
            
            logger.info(f"🔍 {position.ticker}: entry={position.entry_price:.4f}, current={current_price:.4f}, pnl={pnl_check:.3f}%, TP={effective_tp:.2f}%, SL={effective_sl:.2f}%")
            
            should_close, reason, *_ = self.strategy.should_close_position(
                position.figi,
                position.entry_price,
                current_price,
                position.direction,
                take_profit=effective_tp,
                stop_loss=effective_sl
            )
            
            if should_close:
                logger.info(f"🚨 TP/SL СРАБОТАЛ для {position.ticker}! {reason}")
                position.is_closing = True
                positions_to_close.append((position, current_price, reason))
            
            if position.is_closing:
                continue
            
            if should_close:
                logger.info(f"🚨 TP/SL СРАБОТАЛ для {position.ticker}! {reason}")
                position.is_closing = True
                positions_to_close.append((position, current_price, reason))
            # Time-based SL ОТКЛЮЧЁН - используем только TP/SL
            # age_seconds = (datetime.now() - position.entry_time).total_seconds()
            # if age_seconds >= 180 and position.pnl_percent and position.pnl_percent <= 0:
            #     logger.info(f"⏱️ Time SL для {position.ticker}: {age_seconds/60:.0f}min, PnL: {position.pnl_percent:.2f}%")
            #     position.is_closing = True
            #     positions_to_close.append((position, current_price, f"⏱️ Time SL: {position.pnl_percent:.2f}%"))
        
        # МГНОВЕННОЕ закрытие позиций
        for position, price, reason in positions_to_close:
            logger.info(f"🔴 Закрываю {position.ticker} по причине: {reason}")
            result = await self._close_position_instant(position, reason)
            if result:
                results.append(result)
        
        return results
    
    async def check_and_manage_position(self, current_price: float) -> Optional[str]:
        """
        Проверить и управлить одной позицией (для обратной совместимости).
        
        Returns:
            Сообщение о действии или None
        """
        if not self.positions:
            return None
        
        position = self.positions[0]
        
        # Пропускаем если позиция уже закрывается
        if position.is_closing:
            return None
        
        position.update_pnl(current_price)
        
        # TP/SL БЕЗ вычитания комиссии - комиссия учтётся только при закрытии
        effective_tp = self.settings.take_profit_percent
        effective_sl = self.settings.stop_loss_percent
        
        # Логирование для отладки
        logger.info(f"[DEBUG CLOSE] {position.ticker}: entry={position.entry_price}, current={current_price}, tp={effective_tp:.2f}%, sl={effective_sl:.2f}%")
        
        should_close, reason = self.strategy.should_close_position(
            position.figi,
            position.entry_price,
            current_price,
            position.direction,
            take_profit=effective_tp,
            stop_loss=effective_sl
        )
        
        if should_close:
            result = await self._close_position_instant(position, reason)
            return result
        
        # Также закрываем если профит > 1.2% (с запасом на комиссию)
        if position.pnl_percent and position.pnl_percent > 1.2:
            reason = f"🎯 Частичная фиксация: +{position.pnl_percent:.2f}%"
            result = await self._close_position_instant(position, reason)
            return result
        
        return None

    def _get_lot_size(self, figi: str) -> int:
        """Реальный размер лота инструмента с биржи (кэшируется)."""
        cache = getattr(self, "_lot_size_cache", None)
        if cache is None:
            cache = {}
            self._lot_size_cache = cache
        if figi in cache:
            return cache[figi]

        lot = 1
        try:
            info = self.client.get_instrument_by_figi(figi)
            if isinstance(info, dict):
                # GetInstrumentBy возвращает данные вложенными в "instrument"
                instrument = info.get("instrument") or info
                if isinstance(instrument, dict):
                    lot = int(instrument.get("lot") or 1)
        except Exception as e:
            logger.debug(f"Не удалось получить размер лота для {figi}: {e}")

        if lot <= 0:
            lot = 1
        cache[figi] = lot
        return lot

    def _shares_to_lots(self, figi: str, shares: int) -> int:
        """
        Конвертирует количество АКЦИЙ (balance из GetPositions) в ЛОТЫ.

        КРИТИЧНО: Tinkoff GetPositions возвращает balance в АКЦИЯХ,
        а quantity в ордерах задаётся в ЛОТАХ. Путаница приводит к попытке
        продать в lot_size раз больше бумаг, чем есть на счёте:
        «Not enough assets for a margin trade» / «Даже 1 лот не прошёл».
        """
        lot_size = self._get_lot_size(figi)
        shares_abs = abs(int(shares))
        if lot_size <= 1:
            return shares_abs
        return shares_abs // lot_size

    def _ensure_exchange_sl(self) -> None:
        """
        Гарантирует что каждая открытая позиция защищена биржевым стоп-лоссом.

        Позиция может остаться без страховки если:
        - она открыта до появления этой логики;
        - бот перезапустился и потерял exchange_sl_order_id;
        - биржа отклонила стоп при открытии.
        """
        if not self.positions:
            return

        # Отказ биржи не должен повторяться каждый цикл
        if not hasattr(self, "_sl_retry_after"):
            self._sl_retry_after: Dict[str, float] = {}
        if not hasattr(self, "_sl_retry_interval"):
            self._sl_retry_interval = 900.0  # 15 минут

        # Уже размещённые стоп-заявки — чтобы не плодить дубликаты
        existing_stops = []
        try:
            existing_stops = self.client.get_stop_orders() or []
        except Exception as e:
            logger.debug(f"Не удалось получить список стоп-заявок: {e}")

        changed = False
        # ВАЖНО: в этом модуле имя `time` занято классом datetime.time
        # (from datetime import datetime, time), поэтому время берём через datetime.
        now_ts = datetime.now().timestamp()

        for position in self.positions:
            if position.quantity <= 0:
                continue

            want_dir = (
                "STOP_ORDER_DIRECTION_SELL" if position.direction == "BUY"
                else "STOP_ORDER_DIRECTION_BUY"
            )

            # Все стоп-заявки биржи, подходящие под эту позицию.
            # Для SL: цена стопа должна быть НИЖЕ цены входа (страховка от падения)
            matches = []
            for so in existing_stops:
                if not isinstance(so, dict):
                    continue
                if so.get("figi") != position.figi:
                    continue
                if so.get("direction") != want_dir:
                    continue
                try:
                    so_lots = int(so.get("lotsRequested") or so.get("quantity") or 0)
                except (TypeError, ValueError):
                    so_lots = 0
                if so_lots != int(position.quantity):
                    continue
                if so.get("status") not in (None, "STOP_ORDER_STATUS_ACTIVE"):
                    continue
                # Проверяем цену: для SL она должна быть НИЖЕ entry (стоп от падения)
                sp = so.get("stopPrice") or {}
                try:
                    stop_price_val = float(sp.get("units", 0) or 0) + float(sp.get("nano", 0) or 0) / 1e9
                except (TypeError, ValueError):
                    stop_price_val = 0
                if stop_price_val > 0:
                    if position.direction == "BUY" and stop_price_val >= position.entry_price:
                        continue  # Это ТР, не SL
                    if position.direction == "SELL" and stop_price_val <= position.entry_price:
                        continue  # Это ТР (для SELL позиции)
                matches.append(so)

            tracked_id = getattr(position, "exchange_sl_order_id", None)
            tracked_alive = bool(tracked_id) and any(
                m.get("stopOrderId") == tracked_id for m in matches
            )

            # 1) Чистим дубликаты — ВСЕГДА, даже если позиция уже имеет ID.
            #    Лишний стоп при срабатывании продаст бумаги, которых уже нет.
            if len(matches) > 1:
                keep_id = tracked_id if tracked_alive else matches[0].get("stopOrderId")
                for extra in matches:
                    extra_id = extra.get("stopOrderId")
                    if not extra_id or extra_id == keep_id:
                        continue
                    try:
                        self.client.cancel_stop_order(extra_id)
                        logger.warning(f"🧹 {position.ticker}: снят дубль биржевого SL {extra_id}")
                        changed = True
                    except Exception as e:
                        logger.warning(
                            f"⚠️ {position.ticker}: не удалось снять дубль SL {extra_id}: {e}"
                        )
                matches = [m for m in matches if m.get("stopOrderId") == keep_id]

            # 2) Наш стоп жив — просто синхронизируем цену и идём дальше
            if tracked_id and tracked_alive:
                if matches:
                    sp = matches[0].get("stopPrice") or {}
                    try:
                        position.exchange_sl_price = (
                            float(sp.get("units", 0) or 0) + float(sp.get("nano", 0) or 0) / 1e9
                        )
                    except (TypeError, ValueError):
                        pass
                continue

            # 3) Отслеживаемый стоп исчез с биржи (исполнился/снят) — сбрасываем учёт
            if tracked_id and not tracked_alive:
                logger.warning(
                    f"⚠️ {position.ticker}: отслеживаемый SL {tracked_id} больше не на бирже — "
                    f"перевыставляю страховку"
                )
                position.exchange_sl_order_id = None
                position.exchange_sl_price = None
                changed = True

            # 4) Есть подходящий стоп без нашего учёта — «усыновляем»
            if matches:
                adopted = matches[0].get("stopOrderId")
                sp = matches[0].get("stopPrice") or {}
                try:
                    position.exchange_sl_price = (
                        float(sp.get("units", 0) or 0) + float(sp.get("nano", 0) or 0) / 1e9
                    )
                except (TypeError, ValueError):
                    position.exchange_sl_price = None
                position.exchange_sl_order_id = adopted
                self._sl_retry_after.pop(position.figi, None)
                logger.info(
                    f"🛡️ {position.ticker}: найден существующий биржевой SL {adopted} "
                    f"x{position.quantity} @ {position.exchange_sl_price}"
                )
                changed = True
                continue

            # 5) Backoff: если биржа уже отказала (например 30079 «Instrument is not
            #    available for trading» на сессиях moex_morning_weekend), не спамим.
            if now_ts < self._sl_retry_after.get(position.figi, 0.0):
                continue

            sl_direction = "SELL" if position.direction == "BUY" else "BUY"
            stop_id, stop_price, filled = self._place_exchange_sl_with_retry(
                figi=position.figi,
                quantity=int(position.quantity),
                entry_price=position.entry_price,
                direction=sl_direction,
                sl_percent=self.settings.stop_loss_percent,
            )
            if filled:
                logger.warning(
                    f"⚠️ {position.ticker}: биржевой SL исполнился сразу — позицию закрыла биржа"
                )
                continue
            if stop_id:
                position.exchange_sl_order_id = stop_id
                position.exchange_sl_price = stop_price
                self._sl_retry_after.pop(position.figi, None)
                logger.info(
                    f"🛡️ {position.ticker}: биржевой SL дозаказан {stop_id} "
                    f"x{position.quantity} @ {stop_price:.4f}₽"
                )
                changed = True
            else:
                # Повторная попытка через 15 минут (инструмент может быть
                # временно недоступен для стоп-заявок на текущей сессии)
                self._sl_retry_after[position.figi] = now_ts + self._sl_retry_interval
                logger.error(
                    f"❌ {position.ticker}: позиция x{position.quantity} БЕЗ биржевой страховки! "
                    f"Следующая попытка через {int(self._sl_retry_interval / 60)} мин. "
                    f"Работает только программный TP/SL (бот должен быть запущен)."
                )

        if changed:
            save_positions(self.positions)

    def _ensure_exchange_tp(self) -> None:
        """
        Гарантирует что каждая открытая позиция имеет биржевой TP-ордер.
        TP отображается в терминале Т-Инвестиций как стоп-заявка «Тейк-профит».
        """
        if not self.positions:
            return

        if not hasattr(self, "_tp_retry_after"):
            self._tp_retry_after: Dict[str, float] = {}
        if not hasattr(self, "_tp_retry_interval"):
            self._tp_retry_interval = 900.0

        existing_stops = []
        try:
            existing_stops = self.client.get_stop_orders() or []
        except Exception as e:
            logger.debug(f"Не удалось получить список стоп-заявок для TP: {e}")

        changed = False
        now_ts = datetime.now().timestamp()

        for position in self.positions:
            if position.quantity <= 0:
                continue

            # Для TP направление то же, что и для SL (SELL для BUY-позиций)
            want_dir = (
                "STOP_ORDER_DIRECTION_SELL" if position.direction == "BUY"
                else "STOP_ORDER_DIRECTION_BUY"
            )

            # Ищем TP-заявки среди существующих стопов.
            # Для TP: цена стопа должна быть ВЫШЕ цены входа (фиксация прибыли)
            matches = []
            for so in existing_stops:
                if not isinstance(so, dict):
                    continue
                if so.get("figi") != position.figi:
                    continue
                if so.get("direction") != want_dir:
                    continue
                try:
                    so_lots = int(so.get("lotsRequested") or so.get("quantity") or 0)
                except (TypeError, ValueError):
                    so_lots = 0
                if so_lots != int(position.quantity):
                    continue
                if so.get("status") not in (None, "STOP_ORDER_STATUS_ACTIVE"):
                    continue
                # Проверяем цену: для TP она должна быть ВЫШЕ entry (фиксация прибыли)
                sp = so.get("stopPrice") or {}
                try:
                    stop_price_val = float(sp.get("units", 0) or 0) + float(sp.get("nano", 0) or 0) / 1e9
                except (TypeError, ValueError):
                    stop_price_val = 0
                if stop_price_val > 0:
                    if position.direction == "BUY" and stop_price_val <= position.entry_price:
                        continue  # Это SL, не TP
                    if position.direction == "SELL" and stop_price_val >= position.entry_price:
                        continue  # Это SL (для SELL позиции)
                matches.append(so)

            tracked_id = getattr(position, "exchange_tp_order_id", None)
            tracked_alive = bool(tracked_id) and any(
                m.get("stopOrderId") == tracked_id for m in matches
            )

            # 1) Чистим дубликаты TP
            if len(matches) > 1:
                keep_id = tracked_id if tracked_alive else matches[0].get("stopOrderId")
                for extra in matches:
                    extra_id = extra.get("stopOrderId")
                    if not extra_id or extra_id == keep_id:
                        continue
                    try:
                        self.client.cancel_stop_order(extra_id)
                        logger.warning(f"🧹 {position.ticker}: снят дубль биржевого TP {extra_id}")
                        changed = True
                    except Exception as e:
                        logger.warning(
                            f"⚠️ {position.ticker}: не удалось снять дубль TP {extra_id}: {e}"
                        )
                matches = [m for m in matches if m.get("stopOrderId") == keep_id]

            # 2) Наш TP жив — синхронизируем цену
            if tracked_id and tracked_alive:
                if matches:
                    sp = matches[0].get("stopPrice") or {}
                    try:
                        position.exchange_tp_price = (
                            float(sp.get("units", 0) or 0) + float(sp.get("nano", 0) or 0) / 1e9
                        )
                    except (TypeError, ValueError):
                        pass
                continue

            # 3) Отслеживаемый TP исчез (исполнился/снят)
            if tracked_id and not tracked_alive:
                logger.warning(
                    f"⚠️ {position.ticker}: отслеживаемый TP {tracked_id} больше не на бирже"
                )
                position.exchange_tp_order_id = None
                position.exchange_tp_price = None
                changed = True

            # 4) Есть TP без нашего учёта — «усыновляем»
            if matches:
                adopted = matches[0].get("stopOrderId")
                sp = matches[0].get("stopPrice") or {}
                try:
                    position.exchange_tp_price = (
                        float(sp.get("units", 0) or 0) + float(sp.get("nano", 0) or 0) / 1e9
                    )
                except (TypeError, ValueError):
                    position.exchange_tp_price = None
                position.exchange_tp_order_id = adopted
                self._tp_retry_after.pop(position.figi, None)
                logger.info(
                    f"🎯 {position.ticker}: найден существующий биржевой TP {adopted} "
                    f"x{position.quantity} @ {position.exchange_tp_price}"
                )
                changed = True
                continue

            # 5) Backoff
            if now_ts < self._tp_retry_after.get(position.figi, 0.0):
                continue

            tp_direction = "SELL" if position.direction == "BUY" else "BUY"
            tp_price = position.entry_price * (1 + self.settings.take_profit_percent / 100)

            stop_id, stop_price, filled = self._place_exchange_tp_with_retry(
                figi=position.figi,
                quantity=int(position.quantity),
                entry_price=position.entry_price,
                direction=tp_direction,
                tp_percent=self.settings.take_profit_percent,
            )
            if filled:
                logger.warning(
                    f"⚠️ {position.ticker}: биржевой TP исполнился сразу!"
                )
                continue
            if stop_id:
                position.exchange_tp_order_id = stop_id
                position.exchange_tp_price = stop_price
                self._tp_retry_after.pop(position.figi, None)
                logger.info(
                    f"🎯 {position.ticker}: биржевой TP дозаказан {stop_id} "
                    f"x{position.quantity} @ {stop_price:.4f}₽"
                )
                changed = True
            else:
                self._tp_retry_after[position.figi] = now_ts + self._tp_retry_interval
                logger.error(
                    f"❌ {position.ticker}: не удалось разместить биржевой TP! "
                    f"Следующая попытка через {int(self._tp_retry_interval / 60)} мин."
                )

        if changed:
            save_positions(self.positions)

    def _get_min_price_increment(self, figi: str) -> float:
        """Минимальный шаг цены инструмента (кэшируется)."""
        cache = getattr(self, "_min_price_inc_cache", None)
        if cache is None:
            cache = {}
            self._min_price_inc_cache = cache
        if figi in cache:
            return cache[figi]

        inc = 0.01
        try:
            info = self.client.get_instrument_by_figi(figi)
            # ВАЖНО: GetInstrumentBy возвращает данные вложенными в "instrument"
            if isinstance(info, dict):
                instrument = info.get("instrument") or info
                mpi = instrument.get("minPriceIncrement") if isinstance(instrument, dict) else None
                if mpi:
                    value = float(mpi.get("units", 0) or 0) + float(mpi.get("nano", 0) or 0) / 1e9
                    if value > 0:
                        inc = value
        except Exception as e:
            logger.debug(f"Не удалось получить minPriceIncrement для {figi}: {e}")

        cache[figi] = inc
        return inc

    def _round_to_increment(self, price: float, increment: float) -> float:
        """Округляет цену до шага инструмента (биржа принимает только кратные цены)."""
        if increment <= 0:
            return round(price, 6)
        return round(round(price / increment) * increment, 6)

    def _place_exchange_sl_with_retry(
        self,
        figi: str,
        quantity: int,
        entry_price: float,
        direction: str,
        sl_percent: float,
    ):
        """
        Размещает биржевой stop-loss с ретраями.

        Возвращает (stop_order_id, stop_price, filled_now).

        Биржа отклоняет стоп слишком близко к рынку
        (description 30099 / "The price is outside the limits for this instrument") —
        тогда отодвигаем стоп дальше и пробуем снова.
        Цена округляется до minPriceIncrement инструмента.
        """
        if entry_price <= 0 or quantity <= 0:
            return None, None, False

        # Стоп считается от ТЕКУЩЕЙ рыночной цены, а не от цены входа:
        # bid для SELL-стопа (закрываем long), ask для BUY-стопа (закрываем short).
        market_price = entry_price
        try:
            ob = self.client.get_orderbook(figi, 1)
            side = "bids" if direction == "SELL" else "asks"
            quotes = ob.get(side) if isinstance(ob, dict) else None
            if quotes:
                px = quotes[0].get("price", {})
                candidate = float(px.get("units", 0) or 0) + float(px.get("nano", 0) or 0) / 1e9
                if candidate > 0:
                    market_price = candidate
        except Exception as e:
            logger.debug(f"Нет стакана для {figi}, считаю стоп от цены входа: {e}")

        increment = self._get_min_price_increment(figi)

        # Последовательно widening дистанции: штатный SL -> шире -> шире
        attempts_pct = []
        for pct in (sl_percent, max(sl_percent * 2, 1.0), max(sl_percent * 3, 1.5), 2.0, 3.0, 5.0):
            if pct > 0 and pct not in attempts_pct:
                attempts_pct.append(pct)

        for idx, pct in enumerate(attempts_pct):
            sign = -1 if direction == "SELL" else 1
            raw_price = market_price * (1 + sign * pct / 100)
            stop_price = self._round_to_increment(raw_price, increment)
            if stop_price <= 0:
                continue

            try:
                result = self.client.place_stop_loss_order(
                    figi=figi,
                    quantity=quantity,
                    stop_price=stop_price,
                    direction=direction,
                )
            except Exception as e:
                logger.error(f"❌ Исключение при размещении биржевого SL {figi}: {e}")
                continue

            if not isinstance(result, dict) or not result:
                logger.warning(f"⚠️ Пустой ответ API при размещении SL {figi}")
                continue

            status = str(result.get("executionReportStatus", ""))
            # ВАЖНО: PostStopOrder возвращает stopOrderId, а НЕ orderId
            stop_id = result.get("stopOrderId") or result.get("orderId")

            if status == "EXECUTION_REPORT_STATUS_FILL":
                return stop_id, stop_price, True

            if stop_id:
                if idx > 0:
                    logger.info(
                        f"🛡️ Биржевой SL размещён с {idx + 1}-й попытки на {pct:.2f}% "
                        f"(штатный {sl_percent:.2f}% биржа отклонила)"
                    )
                return stop_id, stop_price, False

            msg = f"{result.get('message', '')} {result.get('description', '')}".lower()
            if "30099" in msg or "outside the limits" in msg:
                logger.warning(
                    f"⚠️ Биржа отклонила стоп {stop_price:.4f}₽ ({pct:.2f}%) для {figi}, "
                    f"пробую дальше: {str(result.get('message', '')).strip()}"
                )
                continue

            logger.warning(f"⚠️ Биржевой SL не размещён для {figi}: {result}")
            return None, None, False

        logger.error(
            f"❌ Не удалось разместить биржевой SL для {figi} "
            f"после {len(attempts_pct)} попыток (последняя дистанция {attempts_pct[-1]:.2f}%)"
        )
        return None, None, False

    def _place_exchange_tp_with_retry(
        self,
        figi: str,
        quantity: int,
        entry_price: float,
        direction: str,
        tp_percent: float,
    ):
        """
        Размещает биржевой TAKE-PROFIT с ретраями.

        Возвращает (stop_order_id, stop_price, filled_now).
        Биржа может отклонить TP слишком близко к рынку (30099) —
        отодвигаем дистанцию и пробуем снова.
        """
        if entry_price <= 0 or quantity <= 0:
            return None, None, False

        market_price = entry_price
        try:
            ob = self.client.get_orderbook(figi, 1)
            side = "bids" if direction == "SELL" else "asks"
            quotes = ob.get(side) if isinstance(ob, dict) else None
            if quotes:
                px = quotes[0].get("price", {})
                candidate = float(px.get("units", 0) or 0) + float(px.get("nano", 0) or 0) / 1e9
                if candidate > 0:
                    market_price = candidate
        except Exception as e:
            logger.debug(f"Нет стакана для {figi}, считаю TP от цены входа: {e}")

        increment = self._get_min_price_increment(figi)

        # Дистанции для TP: штатный -> шире
        attempts_pct = []
        for pct in (tp_percent, max(tp_percent * 1.2, 1.5), 2.0, 3.0, 5.0):
            if pct > 0 and pct not in attempts_pct:
                attempts_pct.append(pct)

        for idx, pct in enumerate(attempts_pct):
            sign = 1 if direction == "SELL" else -1
            raw_price = market_price * (1 + sign * pct / 100)
            tp_price = self._round_to_increment(raw_price, increment)
            if tp_price <= 0:
                continue

            try:
                result = self.client.place_stop_loss_order(
                    figi=figi,
                    quantity=quantity,
                    stop_price=tp_price,
                    direction=direction,
                    stop_order_type="STOP_ORDER_TYPE_TAKE_PROFIT",
                )
            except Exception as e:
                logger.error(f"❌ Исключение при размещении биржевого TP {figi}: {e}")
                continue

            if not isinstance(result, dict) or not result:
                logger.warning(f"⚠️ Пустой ответ API при размещении TP {figi}")
                continue

            status = str(result.get("executionReportStatus", ""))
            stop_id = result.get("stopOrderId") or result.get("orderId")

            if status == "EXECUTION_REPORT_STATUS_FILL":
                return stop_id, tp_price, True

            if stop_id:
                if idx > 0:
                    logger.info(
                        f"🎯 Биржевой TP размещён с {idx + 1}-й попытки на {pct:.2f}% "
                        f"(штатный {tp_percent:.2f}% биржа отклонила)"
                    )
                return stop_id, tp_price, False

            msg = f"{result.get('message', '')} {result.get('description', '')}".lower()
            if "30099" in msg or "outside the limits" in msg:
                logger.warning(
                    f"⚠️ Биржа отклонила TP {tp_price:.4f}₽ ({pct:.2f}%) для {figi}, "
                    f"пробую дальше: {str(result.get('message', '')).strip()}"
                )
                continue

            logger.warning(f"⚠️ Биржевой TP не размещён для {figi}: {result}")
            return None, None, False

        logger.error(
            f"❌ Не удалось разместить биржевой TP для {figi} "
            f"после {len(attempts_pct)} попыток"
        )
        return None, None, False

    def _cancel_exchange_sl(self, position) -> None:
        """
        Снимает биржевой стоп-лосс позиции.

        Обязательно перед программным закрытием по TP/SL: иначе после продажи
        бумаг стоп остаётся на бирже и может продать их повторно («сиротский» стоп).
        """
        stop_id = getattr(position, "exchange_sl_order_id", None)
        if not stop_id:
            return
        try:
            self.client.cancel_stop_order(stop_id)
            logger.info(f"🗑️ Биржевой SL снят для {position.ticker}: {stop_id}")
            position.exchange_sl_order_id = None
            position.exchange_sl_price = None
        except Exception as e:
            logger.warning(f"⚠️ Не удалось снять биржевой SL для {position.ticker}: {e}")

    def _cancel_exchange_tp(self, position) -> None:
        """
        Снимает биржевой тейк-профит позиции.

        Обязательно перед программным закрытием: иначе после продажи
        бумаг TP остаётся на бирже и может продать их повторно.
        """
        stop_id = getattr(position, "exchange_tp_order_id", None)
        if not stop_id:
            return
        try:
            self.client.cancel_stop_order(stop_id)
            logger.info(f"🗑️ Биржевой TP снят для {position.ticker}: {stop_id}")
            position.exchange_tp_order_id = None
            position.exchange_tp_price = None
        except Exception as e:
            logger.warning(f"⚠️ Не удалось снять биржевой TP для {position.ticker}: {e}")

    async def open_position(
        self,
        signal,  # ScalpSignal
        quantity: int,
        tp_percent: Optional[float] = None,
        sl_percent: Optional[float] = None
    ) -> Optional[str]:
        """Открыть позицию по сигналу.
        
        Args:
            signal: Сигнал от стратегии
            quantity: Количество лотов
            tp_percent: Динамический TP (берется из settings если None)
            sl_percent: Динамический SL (берется из settings если None)
        """
        if not self.can_open_position():
            return None
        
        if signal.signal_type.value not in ["BUY", "SELL"]:
            return None
        
        # Используем динамические или стандартные значения
        if tp_percent is None:
            tp_percent = self.settings.take_profit_percent
        if sl_percent is None:
            sl_percent = self.settings.stop_loss_percent
        
        try:
            # Разместить ордер
            if self.settings.dry_run:
                result = {
                    "success": True,
                    "dry_run": True,
                    "message": f"[DRY] {signal.signal_type.value} {quantity} {signal.ticker}"
                }
            else:
                # MARKET ордер для мгновенного исполнения
                result = self.client.place_market_order(
                    signal.figi,
                    quantity,
                    signal.signal_type.value,
                    signal.price
                )
            
            # Проверяем результат
            logger.info(f"📊 Ответ API: {result}")
            
            # Если ордер размещён (статус NEW), ждём и проверяем повторно
            order_id = result.get('orderId')
            if result.get("executionReportStatus") == "EXECUTION_REPORT_STATUS_NEW" and order_id:
                logger.info(f"Ордер {order_id} размещён, ждём исполнения...")
                import asyncio
                await asyncio.sleep(10)  # Ждём 10 секунд для исполнения
                # Проверяем статус ордера
                orders = self.client.get_orders()
                for order in orders:
                    if order.get('orderId') == order_id:
                        if order.get('executionReportStatus') == 'EXECUTION_REPORT_STATUS_FILL':
                            logger.info(f"✅ Ордер {order_id} исполнен!")
                            result['executionReportStatus'] = 'EXECUTION_REPORT_STATUS_FILL'
                            break
                else:
                    # Ордер не исполнен, отменяем
                    logger.warning(f"Ордер {order_id} не исполнен за 3 сек, отменяем...")
                    self.client.cancel_order(order_id)
                    return None
            
            if result.get("executionReportStatus") != "EXECUTION_REPORT_STATUS_FILL":
                if result.get("code"):
                    error_msg = str(result.get("message") or result.get("description") or f"Code {result.get('code')}")
                    logger.error(f"Ошибка API: {error_msg}")
                    logger.error(f"DEBUG: figi={signal.figi}, qty={quantity}, dir={signal.signal_type.value}, result={result}")
                else:
                    order_id = result.get('orderId', 'unknown')
                    logger.warning(f"Ордер {order_id} не исполнен, позиция НЕ создана")
                return None
            
            logger.info(f"Ордер исполнен: {result.get('orderId')}")

            # Создать позицию ТОЛЬКО после успешного ордера
            new_position = Position(
                figi=signal.figi,
                ticker=signal.ticker,
                direction=signal.signal_type.value,
                entry_price=signal.price,
                quantity=quantity,
                entry_time=datetime.now(),
                entry_reason=signal.reason
            )
            self.positions.append(new_position)

            # Сохраняем позиции после открытия
            save_positions(self.positions)

            # РАЗМЕЩАЕМ БИРЖЕВОЙ STOP-LOSS как страховку на случай падения бота
            sl_val = sl_percent if sl_percent else self.settings.stop_loss_percent
            sl_direction = "SELL" if signal.signal_type.value == "BUY" else "BUY"

            sl_order_id, sl_price, sl_filled = self._place_exchange_sl_with_retry(
                figi=signal.figi,
                quantity=quantity,
                entry_price=signal.price,
                direction=sl_direction,
                sl_percent=sl_val,
            )

            if sl_filled:
                # SL сразу исполнился (плохая цена) - позиция уже закрыта биржей
                logger.warning(f"⚠️ Биржевой SL сразу исполнился, позиция {signal.ticker} закрыта")
                if new_position in self.positions:
                    self.positions.remove(new_position)
                save_positions(self.positions)
                return None

            if sl_order_id:
                new_position.exchange_sl_order_id = sl_order_id
                new_position.exchange_sl_price = sl_price
                logger.info(
                    f"🛡️ Биржевой SL размещён: stopOrderId={sl_order_id}, "
                    f"price={sl_price:.4f}₽ ({signal.ticker} x{quantity})"
                )
            else:
                # Без страховки позиция не защищена при падении бота -> loudly сообщаем
                logger.error(
                    f"❌ {signal.ticker}: биржевой SL НЕ размещён! "
                    f"Позиция x{quantity} не защищена при падении бота."
                )
                if self.telegram:
                    try:
                        await self.telegram.send_async(
                            f"⚠️ <b>{signal.ticker}</b>: биржевой SL не размещён!\n"
                            f"Позиция x{quantity} не защищена при падении бота."
                        )
                    except Exception:
                        pass

            # Биржевой TP — для отображения в терминале
            tp_val = tp_percent if tp_percent else self.settings.take_profit_percent
            if sl_order_id:  # Только если SL размещён (позиция жива)
                tp_direction = "SELL" if signal.signal_type.value == "BUY" else "BUY"
                tp_order_id, tp_price_placed, tp_filled = self._place_exchange_tp_with_retry(
                    figi=signal.figi,
                    quantity=quantity,
                    entry_price=signal.price,
                    direction=tp_direction,
                    tp_percent=tp_val,
                )
                if tp_filled:
                    logger.warning(f"⚠️ Биржевой TP сразу исполнился, позиция {signal.ticker} закрыта по TP")
                    if new_position in self.positions:
                        self.positions.remove(new_position)
                    save_positions(self.positions)
                    return None
                if tp_order_id:
                    new_position.exchange_tp_order_id = tp_order_id
                    new_position.exchange_tp_price = tp_price_placed
                    logger.info(
                        f"🎯 Биржевой TP размещён: stopOrderId={tp_order_id}, "
                        f"price={tp_price_placed:.4f}₽ ({signal.ticker} x{quantity})"
                    )
                else:
                    logger.warning(f"⚠️ {signal.ticker}: биржевой TP не размещён")

            # НЕ выставляем лимитку при открытии - закрытие только через мониторинг
            # (чтобы избежать двойной комиссии)
            tp_val_for_msg = tp_percent if tp_percent else self.settings.take_profit_percent
            tp_price = signal.price * (1 + tp_val_for_msg / 100) if signal.signal_type.value == "BUY" else signal.price * (1 - tp_val_for_msg / 100)
            
            message = (
                f"✅ <b>Позиция открыта!</b>\n\n"
                f"{'🟢' if signal.signal_type.value == 'BUY' else '🔴'} "
                f"<b>{signal.ticker}</b>\n"
                f"📊 {signal.signal_type.value} {quantity} лотов\n"
                f"💵 Цена: {signal.price:.2f}₽\n"
                f"🎯 TP: {tp_price:.2f}₽\n"
                f"📝 Сигнал: {signal.reason}"
            )
            
            logger.info(f"Позиция открыта: {signal.ticker} {signal.signal_type.value}")
            
            if self.telegram and self.settings.notify_trades:
                await self.telegram.send(message)
            
            return message
            
        except Exception as e:
            logger.error(f"Ошибка открытия позиции: {e}")
            return None
    
    async def _close_position_instant(
        self,
        position: Position,
        reason: str
    ) -> Optional[str]:
        """
        МГНОВЕННОЕ закрытие позиции с retry логикой.
        """
        if position not in self.positions:
            return None
        
        close_direction = "SELL" if position.direction == "BUY" else "BUY"
        
        # Retry logic: до 10 попыток
        for attempt in range(10):
            try:
                # Получить свежую цену из bid/ask
                orderbook = self.client.get_orderbook(position.figi, depth=1)
                current_price = position.entry_price
                
                if position.direction == "BUY":
                    # Продаём -> используем bid
                    bids = orderbook.get('bids', [])
                    if bids:
                        bid = bids[0].get('price', {})
                        current_price = float(bid.get('units', 0)) + float(bid.get('nano', 0)) / 1e9
                else:
                    # Покупаем -> используем ask
                    asks = orderbook.get('asks', [])
                    if asks:
                        ask = asks[0].get('price', {})
                        current_price = float(ask.get('units', 0)) + float(ask.get('nano', 0)) / 1e9
                
                if self.settings.dry_run:
                    result: Dict[str, Any] = {"success": True, "dry_run": True}
                else:
                    result = self.client.place_market_order(
                        position.figi,
                        position.quantity,
                        close_direction,
                        current_price
                    )
                
                order_id = result.get("orderId")
                status = result.get("executionReportStatus")
                
                # Исполнен сразу
                if status == "EXECUTION_REPORT_STATUS_FILL":
                    logger.info(f"✅ МГНОВЕННОЕ закрытие {position.ticker}: исполнен по {current_price:.2f}₽")
                    return await self._finalize_close(position, current_price, reason)
                
                # Ордер размещён, ждём исполнения
                if order_id:
                    logger.info(f"⏳ Ордер {position.ticker} размещён: {order_id}, жду исполнения...")
                    import asyncio
                    for wait_attempt in range(12):  # До 60 секунд
                        await asyncio.sleep(5)
                        
                        # Проверяем ордер
                        orders = self.client.get_orders()
                        for order in orders:
                            if order.get('orderId') == order_id:
                                if order.get('executionReportStatus') == 'EXECUTION_REPORT_STATUS_FILL':
                                    logger.info(f"✅ {position.ticker} исполнен!")
                                    return await self._finalize_close(position, current_price, reason)
                        
                        # Проверяем портфель
                        pos_data = self.client.get_positions()
                        securities = pos_data.get('securities', []) if pos_data else []
                        still_holding = any(s.get('ticker') == position.ticker for s in securities)
                        if not still_holding:
                            logger.info(f"✅ {position.ticker} закрыт (не в портфеле)!")
                            return await self._finalize_close(position, current_price, reason)
                    
                    # Таймаут - отменяем и retry
                    logger.warning(f"⏰ Ордер {position.ticker} не исполнен за 60 сек, отменяю...")
                    try:
                        self.client.cancel_order(order_id)
                    except:
                        pass
                    continue

                # Ошибка - проверяем тип ошибки
                error_msg = str(result.get("message") or result.get("description") or f"Code {result.get('code')}")
                error_code = result.get("code", 0)
                logger.warning(f"⚠️ Ошибка {position.ticker} (попытка {attempt+1}/10): {error_msg} (code={error_code})")

                # Если ошибка margin/account - переходим на поштучную продажу
                if error_code in [78, 30042] or "margin" in error_msg.lower() or "Not enough assets" in error_msg:
                    logger.warning(f"🔄 {position.ticker} - переключаюсь на поштучную продажу из-за маржинальной ошибки")
                    return await self._close_position_piecewise(position, current_price, reason, max_per_order=position.quantity if position.quantity <= 5 else 5)

                if attempt < 9:
                    import asyncio
                    await asyncio.sleep(2)  # Короткая пауза перед retry
                continue
                
            except Exception as e:
                logger.error(f"❌ Исключение при закрытии {position.ticker}: {e}")
                if attempt < 9:
                    import asyncio
                    await asyncio.sleep(2)
                continue

        # Все попытки исчерпаны
        logger.error(f"❌ НЕ УДАЛОСЬ закрыть {position.ticker} за 10 попыток!")
        position.is_closing = False
        return None

    async def _close_position_piecewise(
        self,
        position: Position,
        current_price: float,
        reason: str,
        max_per_order: int = 5
    ) -> Optional[str]:
        """
        Поштучное закрытие позиции (по 1-5 лотов за раз).
        Используется при ошибках margin для крупных позиций.
        """
        close_direction = "SELL" if position.direction == "BUY" else "BUY"
        remaining = position.quantity
        total_executed = 0
        total_cost = 0.0
        batch_size = max_per_order

        logger.info(f"🔄 Поштучное закрытие {position.ticker}: {remaining} лотов по {batch_size}")

        while remaining > 0:
            qty = min(batch_size, remaining)

            try:
                ob = self.client.get_orderbook(position.figi, depth=1)
                if position.direction == "BUY":
                    bids = ob.get('bids', [])
                    if bids:
                        bid = bids[0].get('price', {})
                        current_price = float(bid.get('units', 0)) + float(bid.get('nano', 0)) / 1e9
                else:
                    asks = ob.get('asks', [])
                    if asks:
                        ask = asks[0].get('price', {})
                        current_price = float(ask.get('units', 0)) + float(ask.get('nano', 0)) / 1e9

                if self.settings.dry_run:
                    result: Dict[str, Any] = {"success": True, "dry_run": True, "executionReportStatus": "EXECUTION_REPORT_STATUS_FILL"}
                else:
                    result = self.client.place_market_order(
                        position.figi,
                        qty,
                        close_direction,
                        current_price
                    )

                status = result.get("executionReportStatus", "")
                error_code = result.get("code", 0)

                if status == "EXECUTION_REPORT_STATUS_FILL":
                    total_executed += qty
                    remaining -= qty
                    total_cost += current_price * qty
                    logger.info(f"   ✅ {position.ticker}: продано {qty} из {position.quantity}, осталось {remaining}")

                    if remaining == 0:
                        avg_price = total_cost / total_executed if total_executed > 0 else current_price
                        logger.info(f"✅ {position.ticker} ПОЛНОСТЬЮ закрыт: {total_executed} лотов по средней {avg_price:.4f}₽")
                        return await self._finalize_close(position, avg_price, reason)
                    continue

                if error_code in [78, 30042] or "margin" in str(result.get("message", "")).lower() or "Not enough assets" in str(result.get("message", "")):
                    if batch_size > 1:
                        batch_size = max(1, batch_size // 2)
                        logger.warning(f"   ⚠️ Уменьшаю размер ордера до {batch_size}")
                        continue
                    else:
                        logger.error(f"   ❌ Даже 1 лот не прошёл для {position.ticker}")
                        break

                logger.warning(f"   ⚠️ Ошибка ордера {qty} {position.ticker}: {result.get('message', '')}")
                import asyncio
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"   ❌ Исключение при поштучном закрытии: {e}")
                import asyncio
                await asyncio.sleep(2)

        if remaining > 0:
            logger.error(f"❌ Не удалось закрыть все {position.ticker}: осталось {remaining}")
            position.is_closing = False
            return None

        return None

    async def _finalize_close(
        self,
        position: Position,
        current_price: float,
        reason: str
    ) -> Optional[str]:
        """Завершить закрытие позиции."""
        # СНАЧАЛА снимаем оба биржевых стоп-ордера: если продать бумаги и оставить стоп,
        # он сработает позже и продаст позиции, которых уже нет («сиротский» стоп).
        self._cancel_exchange_sl(position)
        self._cancel_exchange_tp(position)

        position.close(current_price, reason)
        
        if self.stats:
            self.stats.add_trade(position)
        
        if position in self.positions:
            self.positions.remove(position)
        
        # Сохраняем позиции после закрытия
        save_positions(self.positions)
        
        emoji = "✅" if position.pnl and position.pnl > 0 else "❌"
        message = (
            f"{emoji} <b>Позиция закрыта!</b>\n\n"
            f"📈 <b>{position.ticker}</b>\n"
            f"{reason}\n"
            f"💵 Выход: {current_price:.2f}₽\n"
            f"{emoji} PnL: {position.pnl:+.2f}₽ ({position.pnl_percent:+.2f}%)"
        )
        
        logger.info(f"Позиция закрыта: {position.ticker} PnL={position.pnl:.2f}")
        
        if self.telegram and self.settings.notify_trades:
            await self.telegram.send(message)
        
        return message
    
    def get_status(self) -> str:
        """Получить текущий статус трейдера."""
        lines = [
            "📊 <b>Статус скальпинг-бота</b>\n",
        ]
        
        # Время
        lines.append(f"🕐 Время: {datetime.now().strftime('%H:%M:%S')}")
        lines.append(f"📅 Дата: {datetime.now().strftime('%Y-%m-%d')}\n")
        
        # Торговые часы
        trading_hours = "🟢 Открыто" if self.is_trading_hours() else "🔴 Закрыто"
        lines.append(f"{trading_hours} (10:00-18:40)\n")
        
        # МУЛЬТИ-ПОЗИЦИИ: показываем все открытые позиции
        if self.positions:
            lines.append(f"<b>📌 Открытые позиции ({len(self.positions)}):</b>")
            for pos in self.positions:
                lines.append(f"{'🟢' if pos.direction == 'BUY' else '🔴'} {pos.ticker}")
                lines.append(f"   {pos.direction} {pos.quantity} @ {pos.entry_price:.2f}₽")
                if pos.pnl is not None:
                    emoji = "🟢" if pos.pnl > 0 else "🔴"
                    lines.append(f"   {emoji} PnL: {pos.pnl:+.2f}₽ ({pos.pnl_percent:+.2f}%)")
        else:
            lines.append("<b>📌 Позиции:</b> Нет открытых")
        
        lines.append("")
        
        # Статистика дня
        if self.stats:
            trades_limit = "∞" if self.settings.max_trades_per_day >= 999 else self.settings.max_trades_per_day
            lines.append(f"<b>📈 Статистика дня:</b>")
            lines.append(f"   Сделок: {self.stats.trades_count}/{trades_limit}")
            lines.append(f"   PnL: {self.stats.total_pnl:+.2f}₽")
            lines.append(f"   Просадка: {self.stats.max_daily_loss:.2f}₽")
        
        lines.append("")
        lines.append(f"⚙️ Лимиты (с комиссией {self.settings.commission_percent}%):")
        lines.append(f"   Макс. просадка дня: {self.settings.max_daily_loss_percent}%")
        lines.append(f"   Стоп-лосс: {self.settings.effective_stop_loss:.2f}% (включая комиссию)")
        lines.append(f"   Тейк-профит: {self.settings.effective_take_profit:.2f}% (после комиссии)")
        lines.append(f"   Комиссия round-trip: {2 * self.settings.commission_percent}%")
        
        return "\n".join(lines)


def create_trader(client, settings, strategy, telegram_notifier=None) -> ScalpingTrader:
    """Создать экземпляр трейдера."""
    return ScalpingTrader(client, settings, strategy, telegram_notifier)
