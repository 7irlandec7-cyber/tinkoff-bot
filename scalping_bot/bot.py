"""
Scalping Bot - Main Module
"""
import asyncio
import logging
import sys
import os
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scalping_bot.config import get_scalping_settings
from scalping_bot.strategies import get_strategy, ScalpSignal, ScalpingStrategy
from scalping_bot.strategies.rsi_strategy import get_rsi_strategy, RSIEMAStrategy
from scalping_bot.strategies.orderbook_strategy import get_orderbook_strategy, OrderBookScalpingStrategy
from scalping_bot.strategies.advanced_strategy import get_advanced_strategy, AdvancedMultiStrategy
from scalping_bot.strategies.reliable_strategy import ReliableScalpingStrategy
from scalping_bot.strategies.profit_strategy import ProfitStrategy, get_profit_strategy
from scalping_bot.strategies.conservative_strategy import ConservativeStrategy
from scalping_bot.strategies.aggressive_scalper import AggressiveScalper
from scalping_bot.strategies.super_strategy import SuperCombinedStrategy
from scalping_bot.strategies.profit_strategy import ProfitStrategy, get_profit_strategy
from scalping_bot.strategies.pair_trading import get_pair_trading_strategy, PairTradingStrategy
from scalping_bot.strategies.smart_intraday import SmartIntradayStrategy
from scalping_bot.strategies.safe_scalping import SafeScalpingStrategy, SafeScalpingSettings
from scalping_bot.auto_reinvest import get_auto_reinvestor, AutoReinvestor
from scalping_bot.trader import create_trader, ScalpingTrader

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Отправка уведомлений в Telegram."""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
    
    async def send(self, message: str, parse_mode: str = "HTML"):
        """Отправить сообщение."""
        import aiohttp
        
        url = f"{self._base_url}/sendMessage"
        data = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        
        try:
            # Короткий timeout - не блокировать бота
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=data) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"Telegram error: {text}")
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    async def send_async(self, message: str, parse_mode: str = "HTML"):
        """Отправить сообщение в фоне, не блокируя основной цикл."""
        import asyncio
        try:
            asyncio.create_task(self.send(message, parse_mode))
        except Exception as e:
            logger.error(f"Telegram async send error: {e}")


class ScalpingBot:
    """
    Скальпинг-бот для автоматической торговли.
    
    Периодически сканирует рынок, ищет сигналы и открывает позиции.
    """
    
    def __init__(self):
        self.settings = get_scalping_settings()
        self._start_time = time.time()  # Для heartbeat/uptime
        self._opening_position = False  # Блокировка от дублирующих позиций
        self._last_executed_signals = {}  # {figi: timestamp} - защита от дублей
        self._signal_cooldown = 300  # 5 минут между сигналами на один инструмент
        # Выбор стратегии
        if self.settings.strategy_name == "advanced":
            self.strategy = get_advanced_strategy()
            logger.info("📊 Используется Advanced Multi-Strategy")
        elif self.settings.strategy_name == "orderbook":
            self.strategy = get_orderbook_strategy()
            logger.info("📊 Используется OrderBook стратегия")
        elif self.settings.strategy_name == "pair":
            self.strategy = get_pair_trading_strategy()
            logger.info("📊 Используется Pair Trading стратегия")
        elif self.settings.strategy_name == "rsi_ema":
            self.strategy = get_rsi_strategy()
            logger.info("📊 Используется RSI+EMA стратегия")
        elif self.settings.strategy_name == "reliable":
            self.strategy = ReliableScalpingStrategy()
            logger.info("📊 Используется Надёжная стратегия (Support+Volume)")
        elif self.settings.strategy_name == "conservative":
            self.strategy = ConservativeStrategy()
            logger.info("📊 Используется Консервативная стратегия (Поддержка+SL 0.5%)")
        elif self.settings.strategy_name == "aggressive":
            self.strategy = AggressiveScalper(
                tp_percent=self.settings.take_profit_percent,
                sl_percent=self.settings.stop_loss_percent
            )
            logger.info(f"📊 Используется Агрессивный скальпер ({self.settings.take_profit_percent}% TP)")
        elif self.settings.strategy_name == "super":
            self.strategy = SuperCombinedStrategy(
                tp_percent=self.settings.take_profit_percent,
                sl_percent=self.settings.stop_loss_percent
            )
            logger.info(f"🎯 Используется SUPER стратегия (ВСЕ индикаторы должны совпадать!)")
        elif self.settings.strategy_name == "smart_intraday":
            from scalping_bot.strategies.smart_intraday import SmartIntradaySettings
            self.strategy = SmartIntradayStrategy(SmartIntradaySettings(
                tp_percent=self.settings.take_profit_percent,
                sl_percent=self.settings.stop_loss_percent
            ))
            logger.info(f"🧠 Используется Smart Intraday стратегия (EMA+MACD+RSI фильтр+Объём)")
        elif self.settings.strategy_name == "safe_scalping":
            from scalping_bot.strategies.safe_scalping import SafeScalpingSettings
            self.strategy = SafeScalpingStrategy(SafeScalpingSettings(
                tp_percent=self.settings.take_profit_percent,
                sl_percent=self.settings.stop_loss_percent
            ))
            logger.info(f"🛡️ Используется SAFE SCALPING стратегия (RSI<35 для BUY, RSI>65 для SELL, Vol>2x)")
        elif self.settings.strategy_name == "improved":
            from scalping_bot.strategies.improved_scalping import ImprovedScalpingStrategy, ImprovedScalpingSettings
            self.strategy = ImprovedScalpingStrategy(ImprovedScalpingSettings(
                tp_percent=self.settings.take_profit_percent,
                sl_percent=self.settings.stop_loss_percent
            ))
            logger.info(f"⚡ Используется IMPROVED стратегия (RSI<45 для BUY, RSI>55 для SELL, 2/3 индикатора)")
        elif self.settings.strategy_name == "multi":
            from scalping_bot.strategies.multi_indicator_scalping import MultiIndicatorScalpingStrategy, MultiIndicatorSettings
            self.strategy = MultiIndicatorScalpingStrategy(MultiIndicatorSettings(
                tp_percent=self.settings.take_profit_percent,
                sl_percent=self.settings.stop_loss_percent
            ))
            logger.info(f"🎯 Используется MULTI-INDICATOR стратегия (7 индикаторов: RSI+MA+BB+MACD+StochRSI+Vol+OB)")
        elif self.settings.strategy_name == "medium_term":
            from scalping_bot.strategies.medium_term_strategy import MediumTermStrategy, MediumTermSettings
            self.strategy = MediumTermStrategy(MediumTermSettings(
                take_profit_percent=self.settings.take_profit_percent,
                stop_loss_percent=self.settings.stop_loss_percent
            ))
            logger.info(
                f"🎯 Используется СРЕДНЕСРОК стратегия "
                f"(TP={self.settings.take_profit_percent}%, SL={self.settings.stop_loss_percent}%, "
                f"удержание {self.settings.min_hold_minutes}-{self.settings.max_hold_minutes} мин)"
            )
        elif self.settings.strategy_name == "profit":
            self.strategy = get_profit_strategy(
                tp=self.settings.take_profit_percent,
                sl=self.settings.stop_loss_percent
            )
            logger.info(f"💰 Используется PROFIT стратегия (строгий вход 4/5 + фильтр тренда + подтверждение)")
        else:
            self.strategy = get_strategy()
            logger.info("📊 Используется Momentum стратегия")
        
        # Автореинвест
        self.auto_reinvest = get_auto_reinvestor() if self.settings.strategy_name == "advanced" else None
        if self.auto_reinvest:
            logger.info("💹 Автореинвест: ВКЛЮЧЁН")
        
        # Парный трейдинг
        self.pair_trading = get_pair_trading_strategy() if getattr(self.settings, 'pair_trading', False) else None
        
        # Инициализация клиента Tinkoff
        from tinkoff_mcp_server.tinkoff_client import TinkoffClient
        self.client = TinkoffClient(
            token=self.settings.tinkoff_token,
            account_id=self.settings.tinkoff_account_id
        )
        
        # Telegram notifier
        self.telegram: Optional[TelegramNotifier] = None
        if self.settings.telegram_bot_token and self.settings.telegram_chat_id:
            self.telegram = TelegramNotifier(
                self.settings.telegram_bot_token,
                self.settings.telegram_chat_id
            )
        
        # Trader
        self.trader = create_trader(
            self.client,
            self.settings,
            self.strategy,
            self.telegram
        )
        
        # FIGI коды волатильных российских акций для скальпинга
        # Баланс: ~1666₽, поэтому только акции до ~500₽ за лот
        self.watchlist_figi = {
            # Финансы
            "VTBR":   "BBG004730ZJ9",   # ВТБ - 56₽ × 1лот (очень волатильный)
            "UWGN":   "TCS90A0JVBT9",   # ЮGN - 22₽ × 1лот
            "CBOM":   "BBG009GSYN76",   # МКБ - 18₽ × 1лот
            # Нефть/газ
            "SIBN":   "BBG004731471",   # Газпромнефть - 480₽ × 1лот
            # Металлы
            "MAGN":   "BBG004S68507",   # ММК - 22₽ × 10лот
            "ALRS":   "BBG004S68B31",   # Алроса - 22₽ × 10лот
            "NLMK":   "BBG004S681Z8",   # НЛМК - 95₽ × 1лот
            "CHMF":   "BBG004S681L4",   # Северсталь - 900₽ × 1лот
            "RUAL":   "BBG00B45NVR1",   # Русал - 30₽ × 1лот
            # IT/Телеком
            "WUSH":   "TCS00A105EX7",   # Вуш - 55₽ × 1лот
            "VKCO":   "TCS00A106YF0",   # VK - 155₽ × 1лот
            "MTSS":   "BBG004S68DY8",   # МТС - 240₽ × 1лот
            # Энергетика
            "FEES":   "BBG00B45MQ40",   # ФСК - 0.2₽ × 10000лот
            "IRAO":   "BBG004S68J64",   # ИнтерРАО - 3.5₽ × 100лот
            "OGKB":   "BBG004731Y50",   # ОГК-2 - 0.6₽ × 1000лот
            "HYDR":   "BBG004731L65",   # РусГидро - 0.8₽ × 1000лот
            # Химия/удобрения
            "KZOSP":  "BBG0029SG1C1",   # Казаньоргсинтез - 15₽ × 10лот
            "MRKK":   "BBG000V95X70",   # Мариинский - 14₽ × 10лот
            "SELG":   "BBG002458LF8",   # Селигдар - 42₽ × 10лот
            "RUSI":   "BBG0028Z77G9",   # Русолово - 58₽ × 10лот
            # Аптеки/Ритейл
            "APTK":   "BBG000K3STR7",   # Аптека - 6.4₽ × 10лот
            "CARM":   "TCS00A105NV2",   # Кармани - 0.78₽ × 100лот
            # Транспорт
            "AFLT":   "BBG004S681Y3",   # Аэрофлот - 55₽ × 1лот
        }
        
        # Размеры лотов для каждого инструмента
        self.lot_sizes = {
            "VTBR": 1, "UWGN": 1, "CBOM": 1,
            "SIBN": 1, "MAGN": 10, "ALRS": 10, "NLMK": 1, "CHMF": 1, "RUAL": 1,
            "WUSH": 1, "VKCO": 1, "MTSS": 1,
            "FEES": 10000, "IRAO": 100, "OGKB": 1000, "HYDR": 1000,
            "KZOSP": 10, "MRKK": 10, "SELG": 10, "RUSI": 10,
            "APTK": 10, "CARM": 100, "AFLT": 1,
        }
        # Кэш реальных размеров лота с биржи (приоритет над hardcoded)
        self._lot_size_cache: Dict[str, int] = {}

        self._running = False

    def get_lot_size(self, ticker: str, figi: str = "") -> int:
        """
        Реальный размер лота инструмента.

        Приоритет: биржа (GetInstrumentBy) -> hardcoded справочник -> 1.
        Hardcoded значения могут устареть; ошибка в размере лота приводит
        к покупке в N раз больше запланированного (было: APTK x300 вместо x30).
        """
        if figi and figi in self._lot_size_cache:
            return self._lot_size_cache[figi]

        lot = 0
        if figi:
            try:
                info = self.client.get_instrument_by_figi(figi)
                # GetInstrumentBy возвращает данные вложенными в "instrument"
                instrument = info.get("instrument") or info if isinstance(info, dict) else {}
                lot = int(instrument.get("lot") or 0)
            except Exception as e:
                logger.debug(f"Не удалось получить размер лота {ticker}: {e}")

        if lot <= 0:
            lot = int(self.lot_sizes.get(ticker, 1) or 1)
            if lot <= 0:
                lot = 1

        if figi:
            self._lot_size_cache[figi] = lot
        return lot
    
    async def setup_logging(self):
        """Настроить логирование."""
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler("scalping_bot.log")
            ]
        )
    
    async def get_market_prices(self) -> List[dict]:
        """Получить текущие цены для watchlist через FIGI."""
        prices = []
        
        # Получаем цены батчами по 10 штук
        figi_list = list(self.watchlist_figi.values())
        ticker_map = {v: k for k, v in self.watchlist_figi.items()}
        
        try:
            # Получить все цены за один запрос
            price_data = self.client.get_last_prices(figi_list)
            
            for item in price_data:
                figi = item.get("figi") or ""
                ticker = ticker_map.get(figi) or figi or ""
                
                # Parse price (units + nano)
                price_units = item.get("price", {}).get("units", 0)
                price_nano = item.get("price", {}).get("nano", 0)
                price = float(price_units) + float(price_nano) / 1e9
                
                prices.append({
                    "ticker": ticker,
                    "figi": figi,
                    "name": item.get("ticker", ticker),
                    "price": round(price, 2),
                    "volume": 0  # Объём получаем отдельно
                })
                
                logger.debug(f"{ticker}: {price:.2f}₽")
                
        except Exception as e:
            logger.error(f"Ошибка получения цен: {e}")
        
        return prices
    
    async def find_signals(self, prices: List[dict]) -> List[ScalpSignal]:
        """Найти торговые сигналы."""
        signals = []
        
        # Проверяем, нуждается ли стратегия в стакане
        need_orderbook = isinstance(self.strategy, (OrderBookScalpingStrategy, SuperCombinedStrategy, ProfitStrategy))
        orderbooks = {}
        
        if need_orderbook:
            # Получаем стаканы для всех инструментов
            for item in prices:
                try:
                    ob = self.trader.client.get_orderbook(item["figi"], depth=20)
                    if ob:
                        orderbooks[item["figi"]] = ob
                except Exception as e:
                    logger.debug(f"Не удалось получить стакан {item['ticker']}: {e}")
        
        for item in prices:
            # Для OrderBook стратегии передаём стакан
            orderbook = orderbooks.get(item["figi"]) if need_orderbook else None
            
            signal = self.strategy.analyze(
                item["figi"],
                item["ticker"],
                item["price"],
                item["volume"],
                orderbook=orderbook
            )
            
            # Логируем ВСЕ сигналы для отладки (включая HOLD)
            logger.debug(f"[{signal.ticker}] {signal.signal_type.value} ({signal.confidence:.0%}) - {signal.reason}")
            
            if signal.signal_type.value in ["BUY", "SELL"]:
                signals.append(signal)
                logger.info(f"📢 СИГНАЛ: {signal}")
        
        if not signals:
            logger.debug(f"Нет сигналов из {len(prices)} инструментов")
        
        return signals
    
    async def execute_signals(self, signals: List[ScalpSignal]):
        """Исполнить найденные сигналы."""
        import time
        
        # Блокировка от дублирующих позиций
        if self._opening_position:
            logger.debug("Пропуск: уже открывается позиция")
            return
        
        for signal in signals:
            # Проверка кулдауна - защита от дублей
            current_time = time.time()
            last_exec = self._last_executed_signals.get(signal.figi, 0)
            if current_time - last_exec < self._signal_cooldown:
                logger.debug(f"Пропуск {signal.ticker}: кулдаун ({current_time - last_exec:.0f}с)")
                continue
            
            logger.info(f"🔄 Обработка сигнала: {signal.ticker} {signal.signal_type.value} @ {signal.price}")
            
            # Проверяем направление сигнала
            is_buy = signal.signal_type.value == "BUY"
            is_sell = signal.signal_type.value == "SELL"
            
            # Для SELL сигнала - открываем SHORT или закрываем существующую позицию
            if is_sell:
                has_position = any(p.figi == signal.figi for p in self.trader.positions)
                # Если нет позиции и шорты разрешены - открываем шорт
                if not has_position and self.settings.allow_short:
                    logger.info(f"📊 SELL сигнал {signal.ticker} - откроем SHORT")
                    # Продолжаем к открытию шорта
                elif not has_position:
                    logger.debug(f"Пропуск SELL {signal.ticker}: шорты отключены")
                    continue
            
            # Для BUY сигнала - проверяем нет ли уже позиции в этом инструменте
            if is_buy:
                has_position = any(p.figi == signal.figi for p in self.trader.positions)
                if has_position:
                    logger.debug(f"Пропуск BUY {signal.ticker}: позиция уже открыта")
                    continue
                
                # Пропускаем если уже максимум позиций
                if len(self.trader.positions) >= self.settings.max_positions:
                    logger.info(f"Достигнут лимит позиций: {self.settings.max_positions}")
                    break
            
            # Пропускаем если достигнут дневной лимит
            if self.trader.stats and self.trader.stats.trades_count >= self.settings.max_trades_per_day:
                logger.info("Достигнут лимит сделок на день")
                break
            
            # Рассчитать количество лотов с учётом уверенности сигнала
            lot_size = 1  # По умолчанию 1 лот
            
            # Определяем размер позиции на основе уверенности
            confidence = signal.confidence
            
            # Получаем реальный портфель
            portfolio_value = self.trader.get_portfolio_value()
            logger.info(f"💰 Портфель: {portfolio_value:.2f}₽")
            
            # Проверка баланса - НЕ торгуем если units отрицательный
            if portfolio_value <= 0:
                logger.warning(f"⚠️ Баланс не позволяет открыть позицию: {portfolio_value:.2f}₽")
                return
            
            if confidence >= 0.90 and self.settings.use_full_balance:
                # При 90%+ уверенности - используем 50% баланса
                base_invest = portfolio_value * 0.50  # 50% на сделку максимум
                
                # Применяем плечо ТОЛЬКО если явно разрешено
                if self.settings.allow_margin and self.settings.margin_multiplier > 1:
                    base_invest *= self.settings.margin_multiplier
                    logger.info(f"🧮 Маржинальная сделка: x{self.settings.margin_multiplier}")
                
            elif self.settings.use_full_balance:
                # Используем 20% баланса для консервативной торговли
                base_invest = portfolio_value * 0.20
            else:
                # Консервативный расчёт - только 20%
                base_invest = min(
                    self.settings.max_position_size,
                    portfolio_value * 0.20  # 20% портфеля
                )
            
            # Ограничиваем максимальную позицию
            base_invest = min(base_invest, self.settings.max_position_size)
            
            if signal.price <= 0:
                logger.warning(f"Некорректная цена для {signal.ticker}: {signal.price}")
                return  # Пропускаем сигнал

            # Учитываем размер лота (реальный с биржи, hardcoded — только fallback)
            lot_size = self.get_lot_size(signal.ticker, signal.figi)
            if lot_size <= 0:
                lot_size = 1

            # Рассчитываем максимальное количество лотов которое можем купить
            # base_invest в рублях. quantity в API передаётся в ЛОТАХ (не в акциях).
            # 1 лот = lot_size акций, цена лота = signal.price * lot_size
            lot_cost = signal.price * lot_size
            max_lots = int(base_invest / lot_cost) if lot_cost > 0 else 0

            if max_lots < 1:
                # Даже один лот не влезает в бюджет — НЕ форсируем покупку
                # (раньше max(1, ...) покупал лот дороже бюджета = перерасход)
                logger.info(
                    f"⏭️ Пропуск {signal.ticker}: лот стоит {lot_cost:.2f}₽, "
                    f"бюджет {base_invest:.2f}₽ — не хватает на 1 лот"
                )
                return

            quantity = max_lots  # в лотах, БЕЗ умножения на lot_size
            
            # Пропускаем проверку баланса - торгуем несмотря на долг
            # min_cost = signal.price * lot_size
            # if signal.signal_type.value == "BUY" and portfolio_value < min_cost:
            #     logger.warning(f"Недостаточно средств для {signal.ticker}: нужно {min_cost:.2f}₽, есть {portfolio_value:.2f}₽")
            #     return  # Пропускаем сигнал
            
            invested = quantity * signal.price * lot_size
            
            # Используем TP/SL из стратегии если есть
            tp_percent = signal.indicators.get('tp', self.settings.take_profit_percent)
            sl_percent = signal.indicators.get('sl', self.settings.stop_loss_percent)
            
            # Сохраняем в индикаторы для передачи трейдеру
            signal.indicators['tp_percent'] = tp_percent
            signal.indicators['sl_percent'] = sl_percent
            
            logger.info(f"📊 Сигнал {signal.ticker}: confidence={confidence:.0%}, позиция={invested:.0f}₽ ({quantity} лотов)")
            logger.info(f"📊 TP: {tp_percent:.1f}%, SL: {sl_percent:.1f}%")
            
            # Устанавливаем блокировку
            self._opening_position = True
            try:
                result = await self.trader.open_position(signal, quantity, tp_percent=tp_percent, sl_percent=sl_percent)
                # Запоминаем время исполнения - защита от дублей
                if result:
                    self._last_executed_signals[signal.figi] = time.time()
                    logger.info(f"✅ Сигнал {signal.ticker} исполнен, кулдаун {self._signal_cooldown}с")
            finally:
                self._opening_position = False
    
    async def monitor_positions(self, prices: List[dict]):
        """Мониторить ВСЕ открытые позиции (для обратной совместимости)."""
        if not self.trader.positions:
            return
        
        # Создаём мапу цен
        price_map = {item["figi"]: item["price"] for item in prices}
        
        # Мониторим каждую позицию
        for position in self.trader.positions:
            current_price = price_map.get(position.figi)
            if current_price is None:
                continue
            
            # Логирование
            sl_price = position.entry_price * (1 - self.settings.stop_loss_percent / 100)
            tp_price = position.entry_price * (1 + self.settings.take_profit_percent / 100)
            pnl_pct = ((current_price - position.entry_price) / position.entry_price) * 100
            
            logger.info(f"📍 {position.ticker}: {current_price:.2f}₽ | Entry: {position.entry_price:.2f}₽ | PnL: {pnl_pct:+.2f}% | SL: {sl_price:.2f}₽ | TP: {tp_price:.2f}₽")
    
    async def check_daily_reset(self):
        """Проверить и сбросить статистику на новый день."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self.trader.stats and self.trader.stats.date != today:
            logger.info(f"Новый день, сброс статистики")
            self.trader._reset_daily_stats()
            
            if self.telegram:
                await self.telegram.send(
                    f"🔄 <b>Новый торговый день</b>\n"
                    f"📅 {today}"
                )
    
    def _is_best_trading_hours(self) -> bool:
        """Проверить, в лучшее ли время для торговли."""
        if not getattr(self.settings, 'use_time_filter', False):
            return True
        
        import zoneinfo
        from datetime import datetime
        try:
            moscow_tz = zoneinfo.ZoneInfo("Europe/Moscow")
            now = datetime.now(tz=moscow_tz)
        except:
            now = datetime.now()
        current_time = now.time()
        
        # Парсим лучшие часы
        try:
            start_hour, start_min = map(int, self.settings.best_hours_start.split(':'))
            end_hour, end_min = map(int, self.settings.best_hours_end.split(':'))
            
            from datetime import time
            start_time = time(start_hour, start_min)
            end_time = time(end_hour, end_min)
            
            return start_time <= current_time <= end_time
        except:
            return True
    
    def _get_dynamic_tp_sl(self, volatility: float = 0.5) -> tuple:
        """
        Рассчитать динамический TP/SL на основе волатильности.
        
        Args:
            volatility: 0.0-1.0 (низкая-высокая)
        
        Returns:
            (tp_percent, sl_percent)
        """
        if not getattr(self.settings, 'use_dynamic_tp', True):
            return self.settings.take_profit_percent, self.settings.stop_loss_percent
        
        tp_low = getattr(self.settings, 'tp_low', 0.4)
        tp_high = getattr(self.settings, 'tp_high', 1.5)
        sl_low = getattr(self.settings, 'sl_low', 0.5)
        sl_high = getattr(self.settings, 'sl_high', 2.0)
        
        # Интерполяция
        tp = tp_low + (tp_high - tp_low) * volatility
        sl = sl_low + (sl_high - sl_low) * volatility
        
        return tp, sl
    
    async def scan_market(self):
        """Сканировать рынок и выполнять сделки."""
        try:
            # Проверить сброс на новый день
            await self.check_daily_reset()
            
            # Проверить торговые часы
            if not self.trader.is_trading_hours():
                if self._running:
                    logger.info("Вне торговых часов, ожидание...")
                return
            
            # Проверить лучшее время для торговли
            if not self._is_best_trading_hours():
                logger.debug("Не лучшее время для торговли, пропуск...")
                return
            
            # Проверить лимиты (дневной убыток считается от начального депозита)
            if self.trader.stats and self.trader.stats.is_limit_reached(
                self.settings.max_trades_per_day,
                self.settings.max_daily_loss_percent,
                self.settings.initial_balance  # Лимит = 2% × 500₽ = 10₽
            ):
                logger.warning(f"Достигнут дневной лимит! (PnL: {self.trader.stats.max_daily_loss:.2f}₽ от {self.settings.initial_balance:.2f}₽)")
                if self.telegram:
                    await self.telegram.send(
                        "⚠️ <b>Достигнут дневной лимит!</b>\n"
                        "Бот останавливается до завтра."
                    )
                self._running = False
                return
            
            # Получить цены
            prices = await self.get_market_prices()
            
            if not prices:
                logger.warning("Не удалось получить цены")
                return
            
            logger.info(f"Сканирование рынка: {len(prices)}/{len(self.watchlist_figi)} инструментов")
            
            # Мониторить ВСЕ открытые позиции (SL/TP проверка)
            # Сначала логируем все позиции
            await self.monitor_positions(prices)
            # Потом проверяем SL/TP
            close_results = await self.trader.check_and_manage_all_positions(prices)
            for result in close_results:
                logger.info(result)
            
            # Искать сигналы для новых позиций
            if self.trader.can_open_position():
                signals = await self.find_signals(prices)
                
                if signals:
                    # Фильтруем сигналы по открытым FIGI
                    open_figis = {p.figi for p in self.trader.positions}
                    logger.info(f"[DEBUG] open_figis: {open_figis}")
                    available_signals = [s for s in signals if s.figi not in open_figis]
                    
                    if available_signals:
                        # Фильтруем по цене - пропускаем нулевые цены
                        valid_signals = [s for s in available_signals if s.price > 0]
                        if valid_signals:
                            # Исполнить лучший сигнал (с учётом валидности цены)
                            best_signal = max(valid_signals, key=lambda s: s.confidence)
                            logger.info(f"[DEBUG] Executing: {best_signal.ticker} {best_signal.figi} @ {best_signal.price}")
                            await self.execute_signals([best_signal])
                        else:
                            logger.info("[DEBUG] Все сигналы имеют нулевую цену - пропускаем")
                    else:
                        logger.info(f"[DEBUG] No available signals. All signals: {[s.figi for s in signals]}")
            
        except Exception as e:
            import traceback
            logger.error(f"Ошибка сканирования: {e}")
            logger.error(traceback.format_exc())
            if self.telegram and self.settings.notify_errors:
                await self.telegram.send(f"❌ <b>Ошибка:</b>\n{e}")
    
    async def send_status(self):
        """Отправить статус в Telegram."""
        if not self.telegram:
            return
        
        status = self.trader.get_status()
        await self.telegram.send(status)
    
    async def run(self):
        """Запустить бота."""
        logger.info("=" * 50)
        logger.info("🚀 СКАЛЬПИНГ-БОТ ЗАПУЩЕН!")
        logger.info("=" * 50)
        # Получаем реальный портфель
        portfolio_value = self.trader.get_portfolio_value()
        logger.info(f"💰 Портфель: {portfolio_value:.2f}₽")
        logger.info(f"📉 Стоп-лосс: {self.settings.stop_loss_percent}%")
        logger.info(f"🎯 Тейк-профит: {self.settings.take_profit_percent}%")
        logger.info(f"📊 Макс. сделок/день: {self.settings.max_trades_per_day}")
        logger.info(f"📈 Макс. дневной убыток: {self.settings.max_daily_loss_percent}%")
        logger.info("=" * 50)
        
        if self.telegram:
            portfolio_value = self.trader.get_portfolio_value()
            await self.telegram.send(
                f"🚀 <b>Скальпинг-бот запущен!</b>\n\n"
                f"💰 Портфель: {portfolio_value:.2f}₽\n"
                f"📉 Стоп-лосс: {self.settings.stop_loss_percent}%\n"
                f"🎯 Тейк-профит: {self.settings.take_profit_percent}%\n"
                f"⏰ Торговые часы: 10:00-18:40"
            )
        
        self._running = True
        status_counter = 0
        heartbeat_counter = 0

        while self._running:
            try:
                await self.scan_market()

                # Каждые 5 циклов отправлять статус
                status_counter += 1
                if status_counter >= 5 and self.telegram:
                    await self.send_status()
                    status_counter = 0

                # Heartbeat каждые ~5 минут (5 циклов * 60 сек)
                heartbeat_counter += 1
                if heartbeat_counter >= 5:
                    heartbeat_counter = 0
                    uptime_sec = int(time.time() - self._start_time)
                    hours = uptime_sec // 3600
                    minutes = (uptime_sec % 3600) // 60
                    pos_count = len(self.trader.positions)
                    realized = self.trader.stats.total_pnl if self.trader.stats else 0.0
                    unrealized = sum((p.pnl or 0.0) for p in self.trader.positions)
                    logger.info(
                        f"💓 Heartbeat: uptime={hours}ч{minutes}м, позиций={pos_count}, "
                        f"PnL реализованный={realized:+.2f}₽, нереализованный={unrealized:+.2f}₽"
                    )
                    # Сохраняем историю цен для следующего перезапуска
                    save_fn = getattr(self.strategy, "save_history", None)
                    if callable(save_fn):
                        save_fn()

                # Ждать перед следующим циклом
                await asyncio.sleep(self.settings.check_interval)
                
            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки")
                await self._cleanup()
                self._running = False
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                await asyncio.sleep(60)  # Пауза при ошибке
        
        # Остановить бота
        await self._cleanup()
        
        logger.info("Бот остановлен")
        
        if self.telegram:
            await self.telegram.send("🛑 <b>Скальпинг-бот остановлен</b>")
    
    async def stop(self):
        """Остановить бота."""
        await self._cleanup()
        self._running = False
    
    async def _cleanup(self):
        """Очистка при остановке: отмена ордеров."""
        try:
            # Отменить все активные ордера
            orders = self.trader.client.get_orders()
            for order in orders:
                order_id = order.get('orderId')
                if order_id:
                    try:
                        self.trader.client.cancel_order(order_id)
                        logger.info(f"Отменён ордер: {order_id}")
                    except:
                        pass
        except Exception as e:
            logger.error(f"Ошибка очистки: {e}")


async def main():
    """Точка входа."""
    bot = ScalpingBot()
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
