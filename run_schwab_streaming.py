#!/usr/bin/env python3
"""
Entry point to launch the Schwab streaming client for intraday strategies.

Examples:
    # Stream all currently held symbols
    ./run_schwab_streaming.py

    # Stream a watchlist
    DAI_STREAM_SYMBOLS="SPY,AAPL,QQQ" ./run_schwab_streaming.py
"""

import argparse

from schwab_streaming import run_streaming_forever


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start Schwab streaming loop for live trading.")
    parser.add_argument(
        "-s",
        "--symbols",
        nargs="+",
        help="Symbols to stream (defaults to current Schwab positions or DAI_STREAM_SYMBOLS env).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_streaming_forever(symbols=args.symbols)


if __name__ == "__main__":
    main()
