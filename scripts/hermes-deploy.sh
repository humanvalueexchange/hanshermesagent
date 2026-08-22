#!/usr/bin/env bash
# hermes-deploy.sh — Deploy config/SOUL changes from hermes-cfo to live Hermes runtime
# Safe to run at any time — idempotent. No service restart unless changes detected.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTIVE_PROFILE="$(cat "$HOME/.hermes/active_profile" 2>/dev/null || printf 'main')"
HERMES_PROFILE="$HOME/.hermes/profiles/$ACTIVE_PROFILE"
HERMES_HOOKS=~/.hermes/agent-hooks
ENV_FILE=~/.hermes-mcp.env
GATEWAY_UNIT="${HERMES_GATEWAY_UNIT:-hermes-gateway-hanshermesagent.service}"
SKILLS_DIR="$REPO_ROOT/skills/hve"
DRIFT_CHECK="$REPO_ROOT/scripts/hermes-runtime-drift.sh"

echo "╔══════════════════════════════════════════════════╗"
echo "║       Hermes CFO — Deploy                        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. Require a reviewable source tree, then pull latest from repo ───────────
if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  echo "ERROR: repository worktree is dirty. Commit or discard changes before deployment."
  exit 1
fi
echo "→ Pulling latest from hermes-cfo repo..."
cd "$REPO_ROOT"
OLD_HEAD=$(git rev-parse HEAD)
git pull --rebase origin main
echo ""

# ── 2. Load secrets ───────────────────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found. Run hermes-install.sh first."
  exit 1
fi
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a
if [ -z "${HVE_MCP_API_KEY:-}" ]; then
  echo "ERROR: HVE_MCP_API_KEY not set in $ENV_FILE"
  exit 1
fi

# ── 3. Render new config ──────────────────────────────────────────────────────
NEW_CONFIG=$(mktemp)
sed "s/\${HVE_MCP_API_KEY}/$HVE_MCP_API_KEY/g" \
  "$REPO_ROOT/config/hermes-config.template.yaml" \
  > "$NEW_CONFIG"

RESTART_NEEDED=false

# ── 4. Config contract ────────────────────────────────────────────────────────
if [ -f "$HERMES_PROFILE/config.yaml" ]; then
  echo "✅ Preserving active profile config; runtime drift check will validate its managed contract"
else
  cp "$NEW_CONFIG" "$HERMES_PROFILE/config.yaml"
  echo "✅ config.yaml installed (first time)"
  RESTART_NEEDED=true
fi
rm -f "$NEW_CONFIG"

# ── 5. SOUL.md diff ───────────────────────────────────────────────────────────
if ! diff -q "$REPO_ROOT/dotfiles/SOUL.md" "$HERMES_PROFILE/SOUL.md" &>/dev/null 2>&1; then
  echo "→ SOUL.md changed — updating..."
  cp "$REPO_ROOT/dotfiles/SOUL.md" "$HERMES_PROFILE/SOUL.md"
  echo "✅ SOUL.md updated (no restart required — loaded fresh each message)"
else
  echo "✅ SOUL.md — no changes"
fi

# ── 6. Hooks diff ─────────────────────────────────────────────────────────────
mkdir -p "$HERMES_HOOKS"
if ! diff -q "$REPO_ROOT/dotfiles/inject-market-data.sh" \
            "$HERMES_HOOKS/inject-market-data.sh" &>/dev/null 2>&1; then
  echo "→ inject-market-data.sh changed — updating..."
  cp "$REPO_ROOT/dotfiles/inject-market-data.sh" "$HERMES_HOOKS/inject-market-data.sh"
  chmod +x "$HERMES_HOOKS/inject-market-data.sh"
  echo "✅ inject-market-data.sh updated"
  RESTART_NEEDED=true
else
  echo "✅ inject-market-data.sh — no changes"
fi

# ── 6b. Managed user units ────────────────────────────────────────────────────
mkdir -p "$HOME/.config/systemd/user"
for unit in hermes-mcp.service hermes-model-preload.service hve-intake.service hve-intake.path; do
  source_unit="$REPO_ROOT/dotfiles/$unit"
  destination_unit="$HOME/.config/systemd/user/$unit"
  if ! diff -q "$source_unit" "$destination_unit" &>/dev/null 2>&1; then
    cp "$source_unit" "$destination_unit"
    echo "✅ $unit updated"
    RESTART_NEEDED=true
  else
    echo "✅ $unit — no changes"
  fi
done
systemctl --user daemon-reload
if systemctl --user is-active --quiet hermes-mcp.service 2>/dev/null; then
  systemctl --user restart hermes-mcp.service
fi
if systemctl --user is-active --quiet hve-intake.path 2>/dev/null; then
  systemctl --user restart hve-intake.path
fi
if systemctl --user is-active --quiet hermes-model-preload.service 2>/dev/null; then
  systemctl --user restart hermes-model-preload.service
fi

# ── 6c. Native HVE skills validation ──────────────────────────────────────────
skill_count=$(find "$SKILLS_DIR" -mindepth 2 -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')
if [ ! -d "$SKILLS_DIR" ] || [ "$skill_count" -lt 5 ]; then
  echo "ERROR: expected native skills in $SKILLS_DIR (found $skill_count SKILL.md files)"
  exit 1
fi
echo "✅ Native skills available at $SKILLS_DIR ($skill_count files)"

SKILL_DIFF=$(git diff --name-only "$OLD_HEAD" HEAD -- 'skills/**/*.md')
if [ -n "$SKILL_DIFF" ]; then
  echo "→ Native skills changed in repo pull:"
  echo "$SKILL_DIFF"
  RESTART_NEEDED=true
else
  echo "✅ Native skills — no changes in pull"
fi

# ── 7. Restart if needed ──────────────────────────────────────────────────────
if $RESTART_NEEDED; then
  echo ""
  if systemctl --user is-active --quiet "$GATEWAY_UNIT" 2>/dev/null; then
    echo "→ Restarting Hermes gateway (config changed)..."
    systemctl --user restart "$GATEWAY_UNIT"
    sleep 2
    systemctl --user status "$GATEWAY_UNIT" --no-pager | head -6
    echo "✅ Hermes gateway restarted"
  else
    echo "ℹ️  Gateway not running — changes applied, start with:"
    echo "   systemctl --user start $GATEWAY_UNIT"
  fi
else
  echo ""
  echo "ℹ️  No changes requiring restart."
fi

echo ""
echo "→ Checking repository/live runtime drift..."
"$DRIFT_CHECK"

echo ""
echo "Deploy complete ✅  $(date -u '+%Y-%m-%d %H:%M UTC')"
