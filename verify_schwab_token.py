#!/usr/bin/env python3
"""Validate current Schwab token and list available account hashes."""

import json
import sys
from datetime import datetime, timezone

from schwab.auth import easy_client

from config import SCHWAB_CLIENT_ID, SCHWAB_CLIENT_SECRET, SCHWAB_REDIRECT_URI

TOKEN_PATH = "./schwab_tokens.json"


def main() -> None:
    try:
        client = easy_client(
            api_key=SCHWAB_CLIENT_ID,
            app_secret=SCHWAB_CLIENT_SECRET,
            callback_url=SCHWAB_REDIRECT_URI,
            token_path=TOKEN_PATH,
        )
    except Exception as exc:
        print(f"❌ Failed to load Schwab client: {exc}")
        sys.exit(1)

    session = getattr(client, "session", None) or getattr(client, "_session", None)
    token_info = getattr(session, "token", {})
    created_ts = getattr(client, "token_creation_timestamp", None)
    age_sec = None
    if created_ts:
        age_sec = int(datetime.now(timezone.utc).timestamp() - created_ts)

    accounts = client.get_account_numbers().json()

    payload = {
        "access_token_age_sec": age_sec,
        "account_numbers": accounts,
    }

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
