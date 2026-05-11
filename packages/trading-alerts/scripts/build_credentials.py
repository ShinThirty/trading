#!/usr/bin/env python3
"""Build the SSM credentials JSON from ~/.tradingrc and print to stdout.

The Makefile pipes this into `aws ssm put-parameter`. Only [discord] is
required; other sections (e.g., [eia] for the WPSR watcher) are optional and
omitted from the JSON when not present in the rc file.
"""

import configparser
import json
import sys
from pathlib import Path

RC_PATH = Path.home() / ".tradingrc"


def main() -> None:
    if not RC_PATH.exists():
        sys.exit(f"error: {RC_PATH} not found")

    rc = configparser.ConfigParser()
    rc.read(RC_PATH)

    if not (rc.has_section("discord") and rc.has_option("discord", "bot_token")):
        sys.exit("error: [discord] bot_token + channel_id required in ~/.tradingrc")

    out: dict[str, str] = {
        "discord_bot_token": rc["discord"]["bot_token"],
        "discord_channel_id": rc["discord"]["channel_id"],
    }

    # Optional per-watcher credentials. Add new entries here as watchers
    # acquire dependencies on additional credentialed providers.
    if rc.has_section("eia") and rc.has_option("eia", "api_key"):
        out["eia_api_key"] = rc["eia"]["api_key"]

    print(json.dumps(out))


if __name__ == "__main__":
    main()
