#!/usr/bin/env python3
"""Local test runner — invokes the handler with ~/.tradingrc credentials.

Usage:
    uv run python packages/trading-alerts/scripts/invoke_local.py
    uv run python packages/trading-alerts/scripts/invoke_local.py --skip-clock
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
        # Monkey-patch get to return open clock for the CLOCK endpoint
        from trading_clients.tradier_client import TradierClient

        original_get = TradierClient.get

        def patched_get(self, endpoint, request):
            from trading_clients.endpoints.tradier import CLOCK, ClockResponse

            if endpoint is CLOCK:
                return ClockResponse(data={"state": "open"})
            return original_get(self, endpoint, request)

        TradierClient.get = patched_get

    from trading_alerts.handler import handler

    result = handler({}, None)
    print(json.dumps(result, indent=2))

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
