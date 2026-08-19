"""
title: BTC Live Market Data
author: HVE CTO (Claude)
version: 1.1
description: Provides real-time Bitcoin price, 24h stats, and multi-timeframe OHLC context from Kraken. Use this tool whenever current or recent BTC price data is needed. Never estimate or recall prices from memory.
"""

import requests
import json
from datetime import datetime, timezone
from pathlib import Path
import struct


class Tools:
    def __init__(self):
        self.kraken_base = "https://api.kraken.com/0/public"
        self.feather_dir = Path.home() / "freqtrade/user_data/data"

    def get_btc_price(self) -> str:
        """
        Fetch the current live BTC/USD price and 24h market stats from Kraken.
        Always call this tool when asked about Bitcoin price, value, or market level.
        Never use training memory for price data.
        """
        try:
            resp = requests.get(
                f"{self.kraken_base}/Ticker",
                params={"pair": "XXBTZUSD"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("error"):
                return f"Kraken API error: {data['error']}"

            t = data["result"]["XXBTZUSD"]
            last = float(t["c"][0])
            open24 = float(t["o"])
            high24 = float(t["h"][1])
            low24 = float(t["l"][1])
            vol24 = float(t["v"][1])
            vwap24 = float(t["p"][1])
            trades24 = int(t["t"][1])
            change = last - open24
            change_pct = (change / open24) * 100
            direction = "▲" if change >= 0 else "▼"

            fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

            return (
                f"BTC/USD — Live Kraken Feed ({fetched_at})\n"
                f"Price:    ${last:>12,.2f}  {direction} {change_pct:+.2f}% (24h)\n"
                f"24h High: ${high24:>12,.2f}\n"
                f"24h Low:  ${low24:>12,.2f}\n"
                f"24h Open: ${open24:>12,.2f}\n"
                f"24h VWAP: ${vwap24:>12,.2f}\n"
                f"24h Vol:  {vol24:>12,.4f} BTC ({trades24:,} trades)\n"
                f"Source:   Kraken REST API (live)"
            )
        except requests.Timeout:
            return "ERROR: Kraken API timed out. Cannot provide price. Do not estimate."
        except Exception as e:
            return f"ERROR fetching live BTC price: {e}. Do not estimate price from memory."

    def get_btc_ohlc(self, timeframe: str = "1h", candles: int = 24) -> str:
        """
        Fetch recent BTC/USD OHLC candles from Kraken.
        timeframe: one of 1 (1min), 5, 15, 60 (1h), 240 (4h), 1440 (1d)
        candles: number of recent candles to return (max 50)
        """
        tf_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
        interval = tf_map.get(timeframe, 60)
        candles = min(candles, 50)

        try:
            resp = requests.get(
                f"{self.kraken_base}/OHLC",
                params={"pair": "XXBTZUSD", "interval": interval},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("error"):
                return f"Kraken API error: {data['error']}"

            rows = data["result"]["XXBTZUSD"][-candles:]
            fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

            lines = [
                f"BTC/USD OHLC — {timeframe} ({len(rows)} candles, live Kraken, {fetched_at})",
                f"{'Time (UTC)':<20} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>12}",
                "-" * 76,
            ]
            for r in rows:
                ts = datetime.fromtimestamp(r[0], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                lines.append(
                    f"{ts:<20} {float(r[1]):>10,.2f} {float(r[2]):>10,.2f} "
                    f"{float(r[3]):>10,.2f} {float(r[4]):>10,.2f} {float(r[6]):>12,.4f}"
                )
            return "\n".join(lines)

        except Exception as e:
            return f"ERROR fetching OHLC data: {e}. Do not estimate from memory."

    def get_data_freshness(self) -> str:
        """
        Check how fresh the local Kraken BTC/USD feather files are.
        Returns age of each timeframe file so Hermes knows if local data is stale.
        """
        timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]
        now = datetime.now(timezone.utc)
        lines = ["Local Kraken BTC/USD Feather File Freshness Report", "-" * 52]

        for tf in timeframes:
            fpath = self.feather_dir / f"BTC_USD-{tf}.feather"
            if not fpath.exists():
                lines.append(f"  {tf:>4}: ✗ FILE MISSING")
                continue
            mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc)
            age = now - mtime
            hours = age.total_seconds() / 3600
            flag = "✅" if hours < 26 else "⚠️ STALE"
            lines.append(f"  {tf:>4}: {flag}  last updated {hours:.1f}h ago  ({mtime.strftime('%Y-%m-%d %H:%M UTC')})")

        return "\n".join(lines)
