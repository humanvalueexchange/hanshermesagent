#!/usr/bin/env bash
# hermes-update.sh — Daily Hermes agent version check and upgrade
#
# Ownership: Hermes (CFO AI) runs this daily at 03:00 via cron.
# Notify: Hans via Telegram if update available.
# Auto-upgrade: YES (with Telegram notification before + after).
# Manual run: bash scripts/hermes-update.sh
#
# Design principle: Hermes should never be more than 1 week behind upstream.
# Hermes knows its own version and is responsible for flagging when it's stale.
set -euo pipefail

HERMES_DIR=~/.hermes/hermes-agent
VENV_PYTHON="$HERMES_DIR/venv/bin/python"
LOG_DIR=~/.hermes/logs
LOG_FILE="$LOG_DIR/hermes-update-$(date +%Y%m%d).log"
NOTIFY_DAYS_WARN=3   # warn after this many days behind
NOTIFY_DAYS_AUTO=7   # auto-upgrade after this many days behind

mkdir -p "$LOG_DIR"

log() { echo "[$(date -u '+%Y-%m-%d %H:%M UTC')] $*" | tee -a "$LOG_FILE"; }

# ── 1. Get installed version ──────────────────────────────────────────────────
INSTALLED=$("$VENV_PYTHON" -c "from importlib.metadata import version; print(version('hermes-agent'))" 2>/dev/null || echo "unknown")
log "Installed: hermes-agent $INSTALLED"

# ── 2. Get latest available version from PyPI ────────────────────────────────
LATEST=$(curl -s --max-time 10 https://pypi.org/pypi/hermes-agent/json 2>/dev/null | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d['info']['version'])" 2>/dev/null || echo "")

if [ -z "$LATEST" ]; then
  log "Could not reach PyPI — skipping update check"
  exit 0
fi
log "Latest available: hermes-agent $LATEST"

# ── 3. Compare versions ───────────────────────────────────────────────────────
if [ "$INSTALLED" = "$LATEST" ]; then
  log "Up to date ✅"
  exit 0
fi

# Check how many days behind we are
LATEST_DATE=$(curl -s --max-time 10 https://pypi.org/pypi/hermes-agent/json 2>/dev/null | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
files = d['releases'].get('$LATEST', [])
if files:
    print(files[0].get('upload_time','')[:10])
" 2>/dev/null || echo "")

DAYS_BEHIND=0
if [ -n "$LATEST_DATE" ]; then
  TODAY=$(date +%Y-%m-%d)
  DAYS_BEHIND=$(python3 -c "
from datetime import date
latest = date.fromisoformat('$LATEST_DATE')
today = date.fromisoformat('$TODAY')
print((today - latest).days)
" 2>/dev/null || echo "0")
fi

log "Update available: $INSTALLED → $LATEST (released $LATEST_DATE, ${DAYS_BEHIND}d ago)"

# ── 4. Notify Hermes via Telegram if update available ────────────────────────
# Find gateway notification script or use hermes CLI
notify_telegram() {
  local msg="$1"
  # Use hermes MCP or direct Telegram API if configured
  if [ -f ~/.hermes-mcp.env ]; then
    source ~/.hermes-mcp.env 2>/dev/null || true
  fi
  # Log the notification (gateway picks up and routes to Telegram)
  log "TELEGRAM_NOTIFY: $msg"
  # Write to hermes notification queue if available
  if [ -d ~/.hermes/notifications ]; then
    echo "$msg" > ~/.hermes/notifications/update-$(date +%s).txt
  fi
}

# ── 5. Decide: warn or auto-upgrade ──────────────────────────────────────────
if [ "$DAYS_BEHIND" -lt "$NOTIFY_DAYS_WARN" ]; then
  # Fresh release — notify only, let team review release notes first
  notify_telegram "📦 Hermes update available: v$INSTALLED → v$LATEST (released $LATEST_DATE). Review release notes before upgrading. Run: bash ~/hanshermesagent/scripts/hermes-update.sh --upgrade"
  log "Notified — within $NOTIFY_DAYS_WARN day review window, not auto-upgrading"
  exit 0
fi

# Auto-upgrade path (>= NOTIFY_DAYS_WARN days behind, or --upgrade flag)
FORCE_UPGRADE="${1:-}"
if [ "$DAYS_BEHIND" -lt "$NOTIFY_DAYS_AUTO" ] && [ "$FORCE_UPGRADE" != "--upgrade" ]; then
  notify_telegram "📦 Hermes update: v$INSTALLED → v$LATEST is ${DAYS_BEHIND}d old. Auto-upgrade in $((NOTIFY_DAYS_AUTO - DAYS_BEHIND))d or run: bash ~/hanshermesagent/scripts/hermes-update.sh --upgrade"
  log "Notified — not yet at auto-upgrade threshold ($NOTIFY_DAYS_AUTO days)"
  exit 0
fi

# ── 6. Perform upgrade ────────────────────────────────────────────────────────
log "Starting upgrade: $INSTALLED → $LATEST"
notify_telegram "🔄 Hermes self-upgrading: v$INSTALLED → v$LATEST. Gateway will restart in ~60s."

# Stop gateway
systemctl --user stop hermes-gateway.service 2>/dev/null || true
log "Gateway stopped"

# Pull latest tag
TAG=$(curl -s --max-time 10 https://pypi.org/pypi/hermes-agent/json 2>/dev/null | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
# Map PyPI version to git tag (format: v2026.M.D or v2026.M.D.patch)
v = d['info']['version']
parts = v.split('.')
# Latest release date from upload_time
files = d['releases'].get(v, [])
if files:
    ts = files[0].get('upload_time','')[:10].replace('-', '.')
    print(f'v{ts}')
" 2>/dev/null || echo "")

cd "$HERMES_DIR"

if [ -n "$TAG" ]; then
  git fetch --tags --quiet
  if git tag | grep -q "^${TAG}"; then
    git checkout "$TAG" --quiet
    log "Checked out tag: $TAG"
  else
    log "Tag $TAG not found locally, falling back to git pull"
    git checkout main --quiet
    git pull --ff-only --quiet
  fi
else
  log "Could not resolve tag, pulling main"
  git checkout main --quiet
  git pull --ff-only --quiet
fi

# Update dependencies
uv pip install -e . --python "$VENV_PYTHON" --quiet 2>>"$LOG_FILE" || \
  log "WARNING: uv install had errors — check $LOG_FILE"

# Verify new version
NEW_VERSION=$("$VENV_PYTHON" -c "from importlib.metadata import version; print(version('hermes-agent'))" 2>/dev/null || echo "unknown")
log "Upgraded to: $NEW_VERSION"

# Restart gateway
systemctl --user start hermes-gateway.service
sleep 3
if systemctl --user is-active --quiet hermes-gateway.service; then
  log "Gateway restarted ✅"
  notify_telegram "✅ Hermes upgraded to v$NEW_VERSION. Gateway running. Run test-tool-enforcement.sh to validate."
else
  log "ERROR: Gateway failed to start after upgrade"
  notify_telegram "❌ Hermes upgrade to v$NEW_VERSION — GATEWAY FAILED TO START. Manual intervention needed."
  exit 1
fi

# Pull updated hanshermesagent scripts
cd ~/hanshermesagent && git pull --rebase --quiet 2>/dev/null || true

log "Update complete: $INSTALLED → $NEW_VERSION"
