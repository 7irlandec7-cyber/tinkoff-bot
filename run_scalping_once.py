#!/usr/bin/env python3
"""
One-shot bot check for GitHub Actions.
Loads the full bot, runs one market scan cycle, then exits cleanly.
"""
import asyncio
import sys
import os
import logging
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

from dotenv import load_dotenv
load_dotenv()


async def run_once():
    """Init bot, scan market once, log state, exit."""
    from scalping_bot.bot import ScalpingBot

    bot = ScalpingBot()

    # Skip trading hours check for Actions (runs even outside market hours)
    # Just scan once
    await bot.scan_market()

    # Log summary
    pos_count = len(bot.trader.positions)
    portfolio = bot.trader.get_portfolio_value()
    realized = bot.trader.stats.total_pnl if bot.trader.stats else 0.0
    print(f"✅ Done. Portfolio={portfolio:.2f}₽ Positions={pos_count} PnL={realized:+.2f}₽")

    # Persist history for next run
    save_fn = getattr(bot.strategy, "save_history", None)
    if callable(save_fn):
        save_fn()


if __name__ == "__main__":
    asyncio.run(run_once())