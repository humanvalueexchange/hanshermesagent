#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Hermes cron bootstrap is now validation-only."
echo "Cron jobs are managed in the active Hermes profile and deliver through WhatsApp."
echo "Telegram remains the link/PDF ingest channel; Honcho remains the knowledge layer."
exec "${REPO_DIR}/scripts/validate-hermes-cron.sh"
