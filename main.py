"""
Main orchestrator for Polymarket trading bot
Task 1.4.3: Set up APScheduler
"""

import sys
from pathlib import Path
import time
import signal
import sys
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from collectors.collection_loop import collect_and_store_markets, collect_and_store_news
from database.db_manager import init_database
from config import MARKET_POLL_INTERVAL_SEC, NEWS_CHECK_INTERVAL_SEC


# Global variables
scheduler = None
running = True


def setup_scheduler():
    """
    Set up APScheduler with all scheduled jobs.

    Returns:
        BlockingScheduler: Configured scheduler
    """

    global scheduler
    scheduler = BlockingScheduler()

    print("🕐 Setting up scheduler...")
    print("=" * 60)

    # Add market collection job (every 8 hours)
    scheduler.add_job(
        func=collect_and_store_markets,
        trigger=IntervalTrigger(seconds=MARKET_POLL_INTERVAL_SEC),
        id='market_collection',
        name='Collect and store markets',
        replace_existing=True,
        max_instances=1
    )

    hours = MARKET_POLL_INTERVAL_SEC / 3600
    print(f"✅ Market collection scheduled: every {hours} hours")

    # Add news collection job (every 4 hours)
    scheduler.add_job(
        func=collect_and_store_news,
        trigger=IntervalTrigger(seconds=NEWS_CHECK_INTERVAL_SEC),
        id='news_collection',
        name='Collect and store news',
        replace_existing=True,
        max_instances=1
    )

    news_hours = NEWS_CHECK_INTERVAL_SEC / 3600
    print(f"✅ News collection scheduled: every {news_hours} hours")

    # Add startup job (runs immediately)
    scheduler.add_job(
        func=run_startup_tasks,
        trigger='date',
        id='startup_tasks',
        name='Run startup tasks',
        replace_existing=True,
        max_instances=1
    )

    print(f"✅ Startup tasks scheduled: run immediately")

    # Add health check job (every hour)
    scheduler.add_job(
        func=health_check,
        trigger=IntervalTrigger(hours=1),
        id='health_check',
        name='Health check',
        replace_existing=True,
        max_instances=1
    )

    print(f"✅ Health check scheduled: every hour")

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 60)
    print("🚀 Scheduler configured with 4 jobs:")
    print("   1. Market collection (every 8 hours)")
    print("   2. News collection (every 4 hours)")
    print("   3. Startup tasks (immediate)")
    print("   4. Health check (every hour)")
    print("=" * 60)

    return scheduler


def run_startup_tasks():
    """
    Run tasks that should execute on startup.
    """
    print("\n" + "=" * 60)
    print("🚀 RUNNING STARTUP TASKS")
    print("=" * 60)

    try:
        # Initialize database
        print("📊 Initializing database...")
        conn = init_database()
        conn.close()
        print("✅ Database initialized successfully")

        # Run initial market collection
        print("\n📡 Running initial market collection...")
        market_results = collect_and_store_markets()

        if market_results['success']:
            print("✅ Initial market collection completed")
        else:
            print(f"⚠️ Market collection had issues: {market_results.get('error', 'Unknown')}")

        # Run initial news collection
        print("\n📰 Running initial news collection...")
        news_results = collect_and_store_news()

        if news_results['success']:
            print("✅ Initial news collection completed")
        else:
            print(f"⚠️ News collection had issues: {news_results.get('error', 'Unknown')}")

        print("\n" + "=" * 60)
        print("✅ STARTUP TASKS COMPLETED")
        print(f"   Markets: {market_results.get('saved', 0)} saved")
        print(f"   News: {news_results.get('news_saved', 0)} saved")
        print(f"   Ready for scheduled operations!")
        print("=" * 60)

    except Exception as e:
        print(f"❌ Startup tasks failed: {e}")
        import traceback
        traceback.print_exc()


def health_check():
    """
    Periodic health check to ensure bot is running properly.
    """
    try:
        from database.db_manager import get_markets, get_news_events

        # Check database connectivity
        total_markets = len(get_markets())
        recent_news = len(get_news_events({'limit': 10}))

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n💓 Health Check - {timestamp}")
        print(f"   Total markets in DB: {total_markets}")
        print(f"   Recent news items: {recent_news}")
        print(f"   Status: ✅ Running")

    except Exception as e:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n💓 Health Check FAILED - {timestamp}")
        print(f"   Error: {e}")


def signal_handler(signum, frame):
    """
    Handle shutdown signals gracefully.
    """
    global running
    print(f"\n🛑 Received signal {signum}, shutting down gracefully...")

    if scheduler:
        print("⏹️ Stopping scheduler...")
        scheduler.shutdown(wait=True)

    running = False
    print("✅ Shutdown complete")
    sys.exit(0)


def print_scheduled_jobs():
    """
    Print all currently scheduled jobs.
    """
    if not scheduler:
        print("❌ Scheduler not initialized")
        return

    print("\n📅 Scheduled Jobs:")
    print("=" * 50)

    jobs = scheduler.get_jobs()
    for job in jobs:
        # Handle different APScheduler versions
        if hasattr(job, 'next_run_time'):
            next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else "N/A"
        else:
            next_run = "Scheduled"

        print(f"  📋 {job.name}")
        print(f"     ID: {job.id}")
        print(f"     Next run: {next_run}")
        print(f"     Trigger: {type(job.trigger).__name__}")
        print()


def main():
    """
    Main entry point for the Polymarket trading bot.
    """
    print("=" * 60)
    print("🤖 Polymarket Trading Bot - Starting")
    print("=" * 60)
    print(f"   Version: 1.0.0")
    print(f"   Market interval: {MARKET_POLL_INTERVAL_SEC/3600:.1f} hours")
    print(f"   News interval: {NEWS_CHECK_INTERVAL_SEC/3600:.1f} hours")
    print("=" * 60)

    try:
        # Set up scheduler
        scheduler = setup_scheduler()

        # Print initial job schedule
        print_scheduled_jobs()

        # Start the scheduler (this blocks until shutdown)
        print("\n🚀 Starting scheduler... (Press Ctrl+C to stop)")
        print("=" * 60)

        scheduler.start()

    except KeyboardInterrupt:
        print("\n🛑 KeyboardInterrupt received")
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()