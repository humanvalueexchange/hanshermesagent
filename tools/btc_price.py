#!/usr/bin/env python3
"""
btc_price.py — Live BTC/USD price fetcher for Hermes CFO

Queries Kraken public API as the sole market-data system of record.

Usage:
    python3 btc_price.py                      # current price
    python3 btc_price.py --ohlcv 1h           # last closed 1h candle
    python3 btc_price.py --ohlcv 1d           # last closed daily candle

Output (JSON):
    {"price": 82210.5, "source": "kraken", "pair": "BTC/USD", "ts": "2026-05-10T21:07:00Z"}
"""

import sys
import json
import argparse
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

KRAKEN_BASE = "https://api.kraken.com/0/public"
KRAKEN_PAIR = "XXBTZUSD"

TF_MAP = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "1d": 1440,
}


def fetch(url: str, timeout: int = 8) -> dict | list:
    req = Request(url, headers={"User-Agent": "Hermes-CFO/1.0"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_price() -> dict:
    try:
        data = fetch(f"{KRAKEN_BASE}/Ticker?pair={KRAKEN_PAIR}")
        price = float(data["result"][KRAKEN_PAIR]["c"][0])
        return {
            "price": price,
            "price_sats_per_dollar": round(1e8 / price, 2),
            "source": "kraken",
            "pair": "BTC/USD",
            "ts": now_utc(),
        }
    except (URLError, KeyError, ValueError):
        return {"error": "Kraken price unavailable; no alternate source is permitted", "ts": now_utc()}


def get_ohlcv(tf: str) -> dict:
    if tf not in TF_MAP:
        return {"error": f"Unknown timeframe '{tf}'. Use: {list(TF_MAP)}"}

    try:
        data = fetch(f"{KRAKEN_BASE}/OHLC?pair={KRAKEN_PAIR}&interval={TF_MAP[tf]}")
        rows = data["result"][KRAKEN_PAIR]
        # Kraken appends the current open candle; use the last closed candle.
        k = rows[-2]
        open_time = int(k[0])
        close_time = open_time + (TF_MAP[tf] * 60)
        return {
            "timeframe": tf,
            "open_time": datetime.fromtimestamp(open_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "close_time": datetime.fromtimestamp(close_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open":   float(k[1]),
            "high":   float(k[2]),
            "low":    float(k[3]),
            "close":  float(k[4]),
            "volume": float(k[6]),
            "source": "kraken",
            "pair":   "BTC/USD",
            "ts":     now_utc(),
        }
    except (URLError, IndexError, KeyError, ValueError) as e:
        return {"error": f"Kraken OHLCV fetch failed: {e}", "ts": now_utc()}


def main():
    parser = argparse.ArgumentParser(description="Live BTC price fetcher for Hermes CFO")
    parser.add_argument(
        "--ohlcv",
        metavar="TIMEFRAME",
        help="Return last closed OHLCV candle (e.g. 1m 5m 15m 1h 4h 1d)",
    )
    args = parser.parse_args()

    if args.ohlcv:
        result = get_ohlcv(args.ohlcv)
    else:
        result = get_price()

    print(json.dumps(result, indent=2))
    sys.exit(0 if "error" not in result else 1)


if __name__ == "__main__":
    main()
