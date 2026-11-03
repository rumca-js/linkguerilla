import argparse
import subprocess
import sys
from yafr.config import Config, set_console_title


def main():
    set_console_title(f"{Config.INSTANCE_TITLE} - Supervisor")
    parser = argparse.ArgumentParser(
        description=f"Run process_jobs.py and run.py concurrently for {Config.INSTANCE_TITLE}."
    )
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Host address for run.py"
    )
    parser.add_argument(
        "--port", type=int, required=True, help="Port number for run.py"
    )

    args = parser.parse_args()

    # Commands to execute via Poetry
    cmd_jobs = ["poetry", "run", "python", "process_jobs.py"]
    cmd_run = [
        "poetry",
        "run",
        "python",
        "run.py",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]

    processes = []
    try:
        print("Starting process_jobs.py...")
        p_jobs = subprocess.Popen(cmd_jobs)
        processes.append(p_jobs)

        print(f"Starting run.py on {args.host}:{args.port}...")
        p_run = subprocess.Popen(cmd_run)
        processes.append(p_run)

        # Wait for both processes to finish
        for p in processes:
            p.wait()

    except KeyboardInterrupt:
        print("\nShutting down processes...")
        for p in processes:
            p.terminate()
        for p in processes:
            p.wait()
        sys.exit(0)


if __name__ == "__main__":
    main()
