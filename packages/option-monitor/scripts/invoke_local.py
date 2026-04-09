#!/usr/bin/env python3
"""Local test runner — invokes the handler with ~/.tradingrc credentials.

Usage:
    uv run python packages/option-monitor/scripts/invoke_local.py
    uv run python packages/option-monitor/scripts/invoke_local.py --skip-clock
"""

import argparse
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Invoke option monitor locally")
    parser.add_argument(
        "--skip-clock",
        action="store_true",
        help="Skip market clock check (test outside market hours)",
    )
    args = parser.parse_args()

    if args.skip_clock:
        # Monkey-patch raw_get to return open clock for the CLOCK endpoint
        from trading_clients.tradier_client import TradierClient

        original_raw_get = TradierClient.raw_get

        def patched_raw_get(self, endpoint, request):
            from trading_clients.endpoints.tradier import CLOCK

            if endpoint is CLOCK:
                return {"state": "open"}
            return original_raw_get(self, endpoint, request)

        TradierClient.raw_get = patched_raw_get

    from option_monitor.handler import handler

    result = handler({}, None)
    print(json.dumps(result, indent=2))

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
