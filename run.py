#!/usr/bin/env python3
"""
YAFR - Application Entrypoint & CLI Runner.
"""
import argparse
import sys
from yafr.app import create_app
from yafr.config import Config, set_console_title


description = Config.APP_CONSOLE_TITLE


def parse_args():
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--host",
        type=str,
        default=Config.HOST,
        help=f"Host IP to bind server to (default: {Config.HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=Config.PORT,
        help=f"Port to bind server to (default: {Config.PORT})",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=Config.DATABASE_PATH,
        help=f"Path to SQLite database (default: {Config.DATABASE_PATH})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=Config.DEBUG,
        help="Enable Flask debug mode with auto-reload",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    set_console_title(Config.APP_CONSOLE_TITLE)

    # Override config with CLI arguments if specified
    config_dict = {
        "HOST": args.host,
        "PORT": args.port,
        "DATABASE_PATH": args.db,
        "DEBUG": args.debug,
    }
    app = create_app(config_dict)

    print("=" * 60)
    print(f"  {description}")
    print(f"  Running on: http://{args.host}:{args.port}")
    print(f"  Debug mode: {'Enabled' if args.debug else 'Disabled'}")
    print(f"  SQLite DB:  {args.db}")
    print("=" * 60)

    try:
        app.run(host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        print(f"\nShutting down {Config.INSTANCE_TITLE} server. Goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    main()
