#!/usr/bin/env python3

from __future__ import annotations

from common import build_btc_forecast, post_to_mattermost, today_str


def main() -> int:
    try:
        forecast = build_btc_forecast()
    except RuntimeError as exc:
        print("FAIL")
        print(f"- blocker: {exc}")
        return 1

    print(f"PASS {forecast.predicted_price:.1f}")
    print(f"- current BTC/USD price: {forecast.current_price:.1f}")
    print(f"- predicted 09:30 ET price: {forecast.predicted_price:.1f}")
    print(f"- direction: {forecast.direction}")
    print(f"- confidence: {forecast.confidence}")
    print(f"- short rationale: {forecast.rationale}")
    print(f"- invalidation condition: {forecast.invalidation}")
    print(f"- source: {forecast.source}")
    print(f"- run date: {today_str()}")
    direction_emoji = "📈" if forecast.direction == "up" else "📉" if forecast.direction == "down" else "➡️"
    post_to_mattermost(
        f"### {direction_emoji} BTC Forecast — {today_str()}\n"
        f"- Current: **${forecast.current_price:,.0f}**\n"
        f"- Predicted 09:30 ET: **${forecast.predicted_price:,.0f}**\n"
        f"- Direction: {forecast.direction} | Confidence: {forecast.confidence}\n"
        f"- {forecast.rationale}",
        channel_key="TREASURY",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
