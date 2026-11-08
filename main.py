import argparse
import logging
import os
import threading
import sys

from yafr.config import Config, set_console_title
from yafr.app import create_app
from yafr.db.session import init_db, close_session
from yafr.workers.job_executor import JobExecutor


def _start_job_executor(db_path: str, interval: float = 5.0) -> None:
    """Initialise the DB session for this thread and run the job loop forever."""
    try:
        init_db(db_path, sync_schema=False)
    except Exception as err:
        logging.getLogger(__name__).error(
            "Job-executor thread: DB init failed: %s", err
        )
        return

    executor = JobExecutor(auto_refresh_sources=True)
    stop_event = threading.Event()  # never set – runs until the process exits

    try:
        executor.run_loop(interval=interval, stop_event=stop_event)
    finally:
        close_session()


def main():
    set_console_title(f"{Config.INSTANCE_TITLE} - App + Worker")

    parser = argparse.ArgumentParser(
        description=f"Start Flask app and background job executor for {Config.INSTANCE_TITLE}."
    )
    parser.add_argument(
        "--host", type=str, default=Config.HOST, help=f"Host IP to bind (default: {Config.HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=Config.PORT, help=f"Port to bind (default: {Config.PORT})"
    )
    parser.add_argument(
        "--db", type=str, default=Config.DATABASE_PATH,
        help=f"Path to SQLite database (default: {Config.DATABASE_PATH})"
    )
    parser.add_argument(
        "--debug", action="store_true", default=Config.DEBUG,
        help="Enable Flask debug mode with auto-reload"
    )
    parser.add_argument(
        "--interval", type=float, default=5.0,
        help="Job-executor polling interval in seconds (default: 5.0)"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Initialise DB in the main process
    try:
        init_db(args.db, sync_schema=True)
    except Exception as err:
        print(f"Error initialising database at {args.db}: {err}", file=sys.stderr)
        sys.exit(1)

    # When Flask runs in debug/reloader mode it forks a child and sets
    # WERKZEUG_RUN_MAIN=true in that child.  We only want one job-executor
    # thread, so we start it only inside the actual serving process.
    is_reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if not args.debug or is_reloader_child:
        thread = threading.Thread(
            target=_start_job_executor,
            args=(args.db, args.interval),
            daemon=True,
        )
        thread.start()
        logging.getLogger(__name__).info("Job executor daemon thread started.")

    config_dict = {
        "HOST": args.host,
        "PORT": args.port,
        "DATABASE_PATH": args.db,
        "DEBUG": args.debug,
    }
    app = create_app(config_dict)

    print("=" * 60)
    print(f"  {Config.INSTANCE_TITLE}")
    print(f"  Running on: http://{args.host}:{args.port}")
    print(f"  Debug mode: {'Enabled' if args.debug else 'Disabled'}")
    print(f"  SQLite DB:  {args.db}")
    print(f"  Job interval: {args.interval}s")
    print("=" * 60)

    try:
        app.run(host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        print(f"\nShutting down {Config.INSTANCE_TITLE}. Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
