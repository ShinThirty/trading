#!/usr/bin/env python3
"""Run a watcher locally with ~/.tradingrc credentials.

Usage:
    uv run python packages/trading-alerts/scripts/invoke_local.py --trigger naaim
    uv run python packages/trading-alerts/scripts/invoke_local.py --list
"""

import argparse
import json
import logging
import sys


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Invoke a trading-alerts watcher locally")
    parser.add_argument("--trigger", help="Watcher name to run (e.g., naaim, gex)")
    parser.add_argument(
        "--list", action="store_true", help="List available watcher triggers and exit"
    )
    args = parser.parse_args()

    from trading_alerts.handler import WATCHERS, handler

    if args.list:
        print("Available triggers:" if WATCHERS else "No watchers wired yet.")
        for name in sorted(WATCHERS):
            print(f"  {name}")
        return

    if not args.trigger:
        parser.error("--trigger is required (or --list to see available watchers)")

    result = handler({"trigger": args.trigger}, None)
    print(json.dumps(result, indent=2, default=str))

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
