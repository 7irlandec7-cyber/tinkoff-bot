#!/usr/bin/env python3
"""
Scalping Bot Launcher

Usage:
    python run_scalping_bot.py

Requirements:
    - TINKOFF_TOKEN in .env
    - TELEGRAM_BOT_TOKEN in .env
    - TELEGRAM_CHAT_ID in .env (your Telegram chat ID)
"""
import asyncio
import sys
import os
import logging
from pathlib import Path

# Добавить project root
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Настроить логгирование ДО создания бота: иначе logger.info() внутри __init__
# создаёт дефолтный StreamHandler, и последующий basicConfig() игнорируется
# (root уже имеет handler), из-за чего все DEBUG/INFO логи пропадают.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/bot_scalping.log")
    ],
    force=True  # Python 3.8+: перезаписывает handler'ы, созданные логами внутри __init__
)

from dotenv import load_dotenv
load_dotenv()

from scalping_bot.bot import main as scalping_main


def get_chat_id():
    """Get Telegram chat ID from environment or ask user."""
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        return chat_id
    
    print("⚠️ TELEGRAM_CHAT_ID не установлен!")
    print()
    print("Для получения Chat ID:")
    print("1. Откройте Telegram и найдите @userinfobot или @getidsbot")
    print("2. Запустите бота - он покажет ваш Chat ID")
    print("3. Добавьте в .env: TELEGRAM_CHAT_ID=ваш_id")
    print()
    
    chat_id = input("Введите ваш Telegram Chat ID: ").strip()
    if chat_id:
        os.environ["TELEGRAM_CHAT_ID"] = chat_id
        # Save to .env for future runs
        with open(".env", "a") as f:
            f.write(f"\nTELEGRAM_CHAT_ID={chat_id}\n")
        print(f"✅ Chat ID сохранён: {chat_id}")
    
    return chat_id


if __name__ == "__main__":
    print("=" * 60)
    print("📈 SCALPING BOT - Умеренный скальпинг для Тинькофф")
    print("=" * 60)
    print()
    
    # Check for required tokens
    if not os.getenv("TINKOFF_TOKEN"):
        print("❌ Ошибка: TINKOFF_TOKEN не найден!")
        print("Добавьте токен в .env файл.")
        sys.exit(1)
    
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        print("❌ Ошибка: TELEGRAM_BOT_TOKEN не найден!")
        print("Добавьте токен бота в .env файл.")
        sys.exit(1)
    
    # Get chat ID
    chat_id = get_chat_id()
    if not chat_id:
        print("❌ Chat ID обязателен для уведомлений!")
        sys.exit(1)
    
    print()
    print("✅ Все проверки пройдены!")
    print()
    print("Параметры:")
    print(f"  💰 Депозит: {os.getenv('SCALPING_INITIAL_BALANCE', '500')}₽")
    print(f"  📉 Стоп-лосс: {os.getenv('SCALPING_STOP_LOSS', '0.5')}%")
    print(f"  🎯 Тейк-профит: {os.getenv('SCALPING_TAKE_PROFIT', '0.8')}%")
    print(f"  📊 Макс. убыток дня: {os.getenv('SCALPING_MAX_DAILY_LOSS', '2.0')}%")
    strategy_name = os.getenv('SCALPING_STRATEGY', 'momentum')
    strategy_names = {'momentum': 'Momentum', 'rsi_ema': 'RSI+EMA', 'orderbook': 'OrderBook'}
    print(f"  📈 Стратегия: {strategy_names.get(strategy_name, strategy_name)}")
    print()
    
    try:
        asyncio.run(scalping_main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем.")
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)
