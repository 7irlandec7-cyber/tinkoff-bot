#!/usr/bin/env python3
"""
Telegram Bot Launcher

Usage:
    python run_telegram_bot.py

Requirements:
    - TELEGRAM_BOT_TOKEN in .env
    - TINKOFF_TOKEN in .env
"""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from telegram_bot.bot import main
import asyncio


if __name__ == "__main__":
    print("🤖 Starting Tinkoff Invest Telegram Bot...")
    print()
    
    # Check for required tokens
    from dotenv import load_dotenv
    load_dotenv()
    
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        print("❌ Error: TELEGRAM_BOT_TOKEN not found!")
        print("Please add your bot token to the .env file.")
        print("Get a token from @BotFather on Telegram.")
        sys.exit(1)
    
    if not os.getenv("TINKOFF_TOKEN"):
        print("❌ Error: TINKOFF_TOKEN not found!")
        print("Please add your Tinkoff API token to the .env file.")
        sys.exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped.")
    except Exception as e:
        print(f"\n❌ Bot error: {e}")
        sys.exit(1)
