#!/usr/bin/env python3
"""
YAFR - Background Job Processor Script.

Executes background tasks from the SQLite database sequentially, one at a time.
Can be started as a standalone CLI process or scheduled service.

Usage:
    poetry run python process_jobs.py
    poetry run python process_jobs.py --db data/table.db --interval 3.0
    poetry run python process_jobs.py --once
"""

import argparse
from datetime import datetime
import logging
import signal
import sys
import threading
from typing import Dict, Any

from yafr.config import Config, set_console_title
from yafr.db.session import close_session, init_db
from yafr.workers.job_executor import JobExecutor


def parse_args():
    parser = argparse.ArgumentParser(description=Config.WORKER_CONSOLE_TITLE)
    parser.add_argument(
        "--db",
        type=str,
        default=Config.DATABASE_PATH,
        help=f"Path to SQLite database (default: {Config.DATABASE_PATH})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Polling sleep interval in seconds when no jobs are pending (default: 5.0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single job and exit immediately",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Maximum number of jobs to process before exiting (default: unlimited)",
    )
    parser.add_argument(
        "--no-refresh-sources",
        action="store_true",
        help="Disable automatic refresh of outdated sources when job queue is empty",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable detailed debug logging output",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Initialize SQLite database engine
    try:
        init_db(args.db, sync_schema=True)
    except Exception as err:
        print(f"Error initializing database at {args.db}: {err}", file=sys.stderr)
        sys.exit(1)

    stop_event = threading.Event()

    def signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        print(
            f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Received {sig_name}. Stopping worker gracefully..."
        )
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    set_console_title(Config.WORKER_CONSOLE_TITLE)

    print("=" * 64)
    print(f"  {Config.WORKER_CONSOLE_TITLE}")
    print(f"  Database:      {args.db}")
    print(f"  Poll Interval: {args.interval}s")
    print(
        f"  Mode:          {'Single Job (--once)' if args.once else 'Continuous Loop (One at a time)'}"
    )
    print(
        f"  Auto-Sources:  {'Disabled' if args.no_refresh_sources else 'Enabled (when queue empty)'}"
    )
    print("=" * 64)
    print("Worker started. Press Ctrl+C to terminate.")

    executor = JobExecutor(
        auto_refresh_sources=not args.no_refresh_sources,
    )

    def on_job_result(res: Dict[str, Any]):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_label = "[OK]" if res.get("success") else "[FAIL]"
        job_type = res.get("job_type", "unknown")
        job_id = res.get("job_id")
        subject = res.get("subject", "")
        msg = res.get("message", "")

        id_str = f"Job #{job_id}" if job_id else "Auto-Refresh"
        print(
            f"[{now_str}] {status_label} {id_str} [{job_type}] subject='{subject}' -> {msg}"
        )

    try:
        if args.once:
            result = executor.process_one()
            if result and result.get("processed"):
                on_job_result(result)
            else:
                print(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No pending jobs or tasks in queue."
                )
        else:
            executed = executor.run_loop(
                interval=args.interval,
                max_jobs=args.max_jobs,
                stop_event=stop_event,
                callback=on_job_result,
            )
            print(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Worker stopped. Total jobs processed: {executed}"
            )
    finally:
        close_session()


if __name__ == "__main__":
    main()
