#!/usr/bin/env python3
"""
Запуск Finam Forex Bot
"""
import asyncio
import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from finam_forex_bot.bot import main

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Finam Forex Trading Bot")
    print("=" * 60)
    asyncio.run(main())
