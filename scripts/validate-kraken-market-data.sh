#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
freqtrade_config="/home/hans/freqtrade/user_data/config-kraken-paper.json"
data_dir="/home/hans/freqtrade/user_data/data"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

command -v jq >/dev/null || fail "jq is required"

[[ -f "$freqtrade_config" ]] || fail "missing Freqtrade Kraken paper config"
[[ "$(jq -r '.exchange.name' "$freqtrade_config")" == "kraken" ]] || fail "Freqtrade exchange is not Kraken"
jq -e '.exchange.pair_whitelist | index("BTC/USD")' "$freqtrade_config" >/dev/null ||
  fail "Freqtrade allowlist does not contain BTC/USD"

for path in \
  "$repo_dir/tools/btc_price.py" \
  "$repo_dir/mcp/server.py" \
  "$repo_dir/cron/common.py" \
  "$repo_dir/dotfiles/hermes-data-refresh.service" \
  "$repo_dir/config/treasury/market-data.yaml"; do
  [[ ! -e "$path" ]] && fail "missing contract path: $path"
done

if rg -n -i 'binance|btc/usdt|btc_usdt|api\.binance' \
  "$repo_dir/tools/btc_price.py" \
  "$repo_dir/mcp/server.py" \
  "$repo_dir/cron/common.py" \
  "$repo_dir/dotfiles/hermes-data-refresh.service" \
  "$repo_dir/config/treasury/market-data.yaml" >/dev/null; then
  fail "legacy Binance/BTC-USDT reference remains in an active market-data path"
fi

for timeframe in 1m 5m 15m 1h 4h 1d; do
  [[ -f "$data_dir/BTC_USD-${timeframe}.feather" ]] ||
    fail "missing Kraken BTC/USD data file: BTC_USD-${timeframe}.feather"
done

printf 'PASS: Kraken is the active BTC/USD market-data system of record\n'
