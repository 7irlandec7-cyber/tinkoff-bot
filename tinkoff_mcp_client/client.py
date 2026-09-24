#!/usr/bin/env python3
"""
Tinkoff MCP Client - CLI Entry Point

Trading bot that uses Tinkoff Invest API for trading decisions.
"""
import argparse
import asyncio
import logging
import sys
import os
from datetime import datetime
from typing import List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tinkoff_mcp_client.agent import TradingAgent, AgentConfig, TinkoffTradingClient
from tinkoff_mcp_client.strategies import (
    MomentumStrategy,
    TrendFollowingStrategy,
    MeanReversionStrategy,
)


def setup_logging(level: str = "INFO", log_file: Optional[str] = None):
    """Setup logging configuration."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        handlers=handlers
    )


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Tinkoff MCP Trading Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default strategy (trend following)
  export TINKOFF_TOKEN=your_token
  python -m tinkoff_mcp_client.client

  # Run with momentum strategy
  python -m tinkoff_mcp_client.client --strategy momentum

  # Dry-run mode (default)
  python -m tinkoff_mcp_client.client --dry-run

  # Live trading (CAREFUL!)
  python -m tinkoff_mcp_client.client --live

  # Custom tickers
  python -m tinkoff_mcp_client.client --tickers SBER GAZP LKOH

  # Single analysis cycle
  python -m tinkoff_mcp_client.client --once
        """
    )
    
    parser.add_argument(
        "--strategy", "-s",
        choices=["momentum", "trend_following", "mean_reversion"],
        default="trend_following",
        help="Trading strategy to use"
    )
    
    parser.add_argument(
        "--tickers", "-t",
        nargs="+",
        default=["SBER", "GAZP", "VTBR"],
        help="Tickers to analyze"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry run mode (no real trades)"
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="Live trading mode (REAL MONEY)"
    )
    
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run single analysis cycle and exit"
    )
    
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Analysis interval in seconds (default: 300)"
    )
    
    parser.add_argument(
        "--max-position",
        type=float,
        default=10000.0,
        help="Maximum position size in rubles"
    )
    
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.6,
        help="Minimum signal confidence (0.0-1.0)"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level"
    )
    
    parser.add_argument(
        "--log-file",
        help="Log file path"
    )
    
    return parser.parse_args()


def print_banner():
    """Print startup banner."""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                  Tinkoff MCP Trading Agent                  ║
╠══════════════════════════════════════════════════════════════╣
║  ⚠️  IMPORTANT: This software is for educational purposes.   ║
║  Trading stocks involves risk of loss.                        ║
║  Use --dry-run mode for testing.                             ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


async def run_agent(args):
    """Run the trading agent."""
    from dotenv import load_dotenv
    
    logger = logging.getLogger(__name__)
    
    # Load environment variables from .env file
    load_dotenv()
    
    # Get token
    token = os.environ.get("TINKOFF_TOKEN", "")
    if not token:
        logger.error("ERROR: TINKOFF_TOKEN environment variable is not set!")
        logger.error("")
        logger.error("Please set your Tinkoff API token:")
        logger.error("  1. Copy .env.example to .env:")
        logger.error("     cp .env.example .env")
        logger.error("")
        logger.error("  2. Edit .env and add your token:")
        logger.error("     TINKOFF_TOKEN=your_token_here")
        logger.error("")
        logger.error("  Or export directly:")
        logger.error("     export TINKOFF_TOKEN=your_token")
        logger.error("")
        logger.error("Get your token at: https://www.tinkoff.ru/invest/settings/")
        return
    
    account_id = os.environ.get("TINKOFF_ACCOUNT_ID") or None
    
    # Create agent configuration
    config = AgentConfig(
        strategy=args.strategy,
        tickers=args.tickers,
        dry_run=not args.live,
        check_interval=args.interval,
        max_position_size=args.max_position,
        min_confidence=args.min_confidence,
        token=token,
        account_id=account_id,
    )
    
    # Print configuration
    logger.info("=" * 60)
    logger.info("Agent Configuration")
    logger.info("=" * 60)
    logger.info(f"Strategy:        {config.strategy}")
    logger.info(f"Tickers:         {', '.join(config.tickers)}")
    logger.info(f"Mode:            {'DRY-RUN' if config.dry_run else 'LIVE TRADING'}")
    logger.info(f"Interval:        {config.check_interval}s")
    logger.info(f"Max Position:    {config.max_position_size:,.0f} RUB")
    logger.info(f"Min Confidence:  {config.min_confidence:.2f}")
    logger.info(f"Token:           {'✓ Set' if token else '✗ Not set'}")
    logger.info(f"Account ID:      {account_id or 'Auto-detect'}")
    logger.info("=" * 60)
    
    if not config.dry_run:
        logger.warning("⚠️" * 20)
        logger.warning("LIVE TRADING MODE - Real orders will be placed!")
        logger.warning("You are about to spend REAL MONEY!")
        logger.warning("⚠️" * 20)
        response = input("\nType 'yes' to continue with REAL trading: ")
        if response.lower() != 'yes':
            logger.info("Cancelled by user.")
            return
    
    # Create Tinkoff client
    client = TinkoffTradingClient(token=token, account_id=account_id)
    
    # Create trading agent
    agent = TradingAgent(config=config, client=client)
    
    try:
        if args.once:
            # Single analysis cycle
            results = await agent.run_analysis_cycle()
            print("\n" + "=" * 60)
            print("Summary")
            print("=" * 60)
            print(f"Analyzed:  {results['analyzed']} instruments")
            print(f"Signals:   {len(results['signals'])}")
            print(f"Errors:    {len(results['errors'])}")
            
            if results['signals']:
                print("\nSignals Generated:")
                for signal in results['signals']:
                    print(f"  [{signal['action']}] {signal['ticker']} "
                          f"{signal['quantity']} lots @ {signal.get('price', 0):.2f}")
                    print(f"           Confidence: {signal['confidence']:.2f}")
                    print(f"           {signal['reason']}")
            
            if results['errors']:
                print("\nErrors:")
                for error in results['errors']:
                    print(f"  {error['ticker']}: {error['error']}")
            
            # Print decision history
            decisions = agent.get_decision_history()
            if decisions:
                print(f"\n{len(decisions)} decisions logged.")
        else:
            # Continuous loop
            logger.info("Starting continuous trading loop...")
            logger.info("Press Ctrl+C to stop.")
            
            cycle = 0
            while True:
                cycle += 1
                logger.info(f"\n{'='*60}")
                logger.info(f"Cycle #{cycle}")
                logger.info(f"{'='*60}")
                
                try:
                    results = await agent.run_analysis_cycle()
                    
                    # Show signals
                    if results['signals']:
                        for signal in results['signals']:
                            mode = "[DRY-RUN]" if config.dry_run else "[LIVE]"
                            print(f"  {mode} {signal['action']} {signal['quantity']}x "
                                  f"{signal['ticker']} @ {signal.get('price', 0):.2f}")
                    
                except Exception as e:
                    logger.error(f"Error in cycle #{cycle}: {e}")
                
                logger.info(f"\nSleeping for {config.check_interval} seconds...")
                logger.info("Press Ctrl+C to stop...")
                await asyncio.sleep(config.check_interval)
    
    except KeyboardInterrupt:
        logger.info("\nShutdown requested...")
    finally:
        # Print final decision history
        decisions = agent.get_decision_history()
        if decisions:
            logger.info("\n" + "=" * 60)
            logger.info("Decision History (Last 10)")
            logger.info("=" * 60)
            for decision in decisions[-10:]:
                status = "[DRY-RUN]" if decision["dry_run"] else "[LIVE]"
                print(f"  {status} {decision['timestamp'][:19]} "
                      f"{decision['action']:4s} {decision['quantity']:3d}x "
                      f"{decision['ticker']} @ {decision['price']:.2f}")
        
        await agent.close()
        logger.info("\nAgent shutdown complete.")


def main():
    """Main entry point."""
    args = parse_args()
    
    # Setup logging
    setup_logging(args.log_level, args.log_file)
    
    # Print banner
    print_banner()
    
    # Run agent
    try:
        asyncio.run(run_agent(args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
