#!/usr/bin/env python3
"""
Manual Schwab OAuth 2.0 helper.

This script mirrors the flow described in Schwab's Trader API documentation and
the community examples (e.g. Schwabdev).  Use it when you need to bootstrap or
refresh the token file outside of the schwab-py helper.

Usage examples:
    # Full three-legged flow (opens browser, saves tokens)
    ./schwab_manual_auth.py --save

    # Refresh using existing refresh_token in schwab_tokens.json
    ./schwab_manual_auth.py --refresh --save

Environment variables:
    SCHWAB_CLIENT_ID       (required) - App Key / Client ID
    SCHWAB_CLIENT_SECRET   (required) - App Secret
    SCHWAB_REDIRECT_URI    (optional) - defaults to https://127.0.0.1
    SCHWAB_TOKEN_FILE      (optional) - defaults to ./schwab_tokens.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import socket
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"


def _init_env() -> None:
    """Load environment variables from .env if present."""
    load_dotenv(override=False)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"❌ Environment variable {name} is required.", file=sys.stderr)
        sys.exit(1)
    return value


def _build_basic_auth_header(client_id: str, client_secret: str) -> str:
    credentials = f"{client_id}:{client_secret}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return f"Basic {encoded}"


def _construct_auth_url(client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def _ensure_port_available(redirect_uri: str) -> None:
    """
    Preflight check: ensure the redirect port is free before starting the OAuth local server.
    Exits with a clear message if the port is already in use.
    """
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if not port:
        # Default ports (mostly irrelevant here, but keep behavior sane)
        port = 443 if parsed.scheme == "https" else 80
    # Only check localhost-style hosts to avoid false positives on remote hosts
    if host not in {"127.0.0.1", "localhost"}:
        return
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
    except OSError:
        print(f"❌ Port {port} on {host} is already in use. Stop the process using it, then retry.", file=sys.stderr)
        print(f"   Hint: lsof -i tcp:{port}  # find the PID to kill", file=sys.stderr)
        print("   Or update SCHWAB_REDIRECT_URI and your Schwab app redirect to a different port (consistently).", file=sys.stderr)
        sys.exit(1)


def _prompt_for_code(auth_url: str) -> str:
    print("\n🔗 Open the following URL in your browser to authorize the app:")
    print(auth_url)
    opened = webbrowser.open(auth_url)
    if not opened:
        print("⚠️  Could not launch browser automatically. Copy the URL above manually.")

    print("\n📋 After approving access, paste the full redirected URL here:")
    returned_url = input("> ").strip()
    if not returned_url:
        print("❌ No URL provided; aborting.", file=sys.stderr)
        sys.exit(1)

    parsed = urllib.parse.urlparse(returned_url)
    query = urllib.parse.parse_qs(parsed.query)
    code = query.get("code", [None])[0]
    if not code and parsed.fragment:
        fragment_query = urllib.parse.parse_qs(parsed.fragment)
        code = fragment_query.get("code", [None])[0]

    if not code:
        print("❌ Could not locate 'code' parameter in the returned URL.", file=sys.stderr)
        sys.exit(1)

    return urllib.parse.unquote(code)


def _exchange_code_for_tokens(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    authorization_code: str,
) -> dict:
    headers = {
        "Authorization": _build_basic_auth_header(client_id, client_secret),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    payload = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": redirect_uri,
    }
    response = requests.post(TOKEN_URL, headers=headers, data=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    return _enrich_token_payload(data)


def _refresh_tokens(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> dict:
    headers = {
        "Authorization": _build_basic_auth_header(client_id, client_secret),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    response = requests.post(TOKEN_URL, headers=headers, data=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    return _enrich_token_payload(data)


def _enrich_token_payload(data: dict) -> dict:
    """
    Add helpful metadata (UTC timestamps) so the file can be inspected or
    reused by higher-level clients.
    """
    now = datetime.now(timezone.utc)
    access_expires_in = int(data.get("expires_in", 0))
    refresh_token_ttl = int(data.get("refresh_token_expires_in", 0))
    data["fetched_at"] = now.isoformat()
    if access_expires_in:
        data["access_expires_at"] = (now + timedelta(seconds=access_expires_in)).isoformat()
    if refresh_token_ttl:
        data["refresh_expires_at"] = (now + timedelta(seconds=refresh_token_ttl)).isoformat()
    return data


def _save_tokens(token_path: Path, tokens: dict, creation_ts: Optional[int] = None) -> None:
    if creation_ts is None:
        creation_ts = int(datetime.now(timezone.utc).timestamp())
    wrapped = {
        "creation_timestamp": creation_ts,
        "token": tokens,
    }
    token_path.write_text(json.dumps(wrapped, indent=2))
    print(f"💾 Tokens written to {token_path}")


def load_existing_tokens(token_path: Path) -> Optional[dict]:
    if not token_path.exists():
        return None
    try:
        raw = json.loads(token_path.read_text())
        if isinstance(raw, dict) and "token" in raw:
            return raw
        return {"token": raw}
    except Exception as exc:
        print(f"⚠️  Could not parse existing token file ({exc}). Ignoring.", file=sys.stderr)
        return None


def main() -> None:
    _init_env()
    parser = argparse.ArgumentParser(description="Manual Schwab OAuth helper.")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Persist tokens to SCHWAB_TOKEN_FILE (default: ./schwab_tokens.json).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh tokens using the refresh_token in SCHWAB_TOKEN_FILE.",
    )
    parser.add_argument(
        "--redirect-uri",
        default=os.getenv("SCHWAB_REDIRECT_URI", "https://127.0.0.1"),
        help="Override redirect URI (defaults to env or https://127.0.0.1).",
    )
    args = parser.parse_args()

    client_id = _require_env("SCHWAB_CLIENT_ID")
    client_secret = _require_env("SCHWAB_CLIENT_SECRET")
    token_path = Path(os.getenv("SCHWAB_TOKEN_FILE", "schwab_tokens.json"))

    creation_ts: Optional[int] = None
    if args.refresh:
        existing = load_existing_tokens(token_path)
        if not existing or "token" not in existing or "refresh_token" not in existing["token"]:
            print("❌ No refresh_token available. Run without --refresh first.", file=sys.stderr)
            sys.exit(1)

        creation_ts = existing.get("creation_timestamp")
        print("🔄 Refreshing tokens...")
        tokens = _refresh_tokens(client_id, client_secret, existing["token"]["refresh_token"])
    else:
        _ensure_port_available(args.redirect_uri)
        auth_url = _construct_auth_url(client_id, args.redirect_uri)
        code = _prompt_for_code(auth_url)
        print("🔑 Exchanging authorization code for tokens...")
        tokens = _exchange_code_for_tokens(client_id, client_secret, args.redirect_uri, code)

    print("\n✅ Token response:")
    print(json.dumps(tokens, indent=2))

    if args.save:
        _save_tokens(token_path, tokens, creation_ts)
        print(
            "\n⚠️  Reminder: Schwab refresh tokens expire after 7 days. "
            "Re-run this helper (with --refresh) before then, or re-authorize."
        )


if __name__ == "__main__":
    main()
