"""Entry point for the Running Coach CLI.

Usage:
    # First time setup:
    python auth.py

    # Every subsequent run:
    python cli.py
"""
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import TOKENS_FILE, get_config


def check_setup():
    try:
        config = get_config()
    except KeyError as e:
        print(f"Missing environment variable: {e}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    if not TOKENS_FILE.exists() or not config.access_token:
        print("Strava not authenticated yet.")
        print("Run:  python auth.py")
        sys.exit(1)


def main():
    check_setup()

    from coach.cli import run_agent

    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\nGoodbye! Keep running!")


if __name__ == "__main__":
    main()
