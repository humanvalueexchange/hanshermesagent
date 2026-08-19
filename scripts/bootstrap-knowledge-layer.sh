#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="${HOME}/hermes-cfo"
ROOT="/hve-library"
RUNTIME_DIR="${HOME}/.hve-knowledge"
VENV_DIR="${RUNTIME_DIR}/venv"
VAULT_DIR="${ROOT}/vault/hve-knowledge-vault"

echo "== Creating knowledge-layer directories =="
sudo install -d -m 755 -o hans -g hans \
  "${ROOT}" \
  "${ROOT}/intake" \
  "${ROOT}/intake/failed" \
  "${ROOT}/intake/inbox" \
  "${ROOT}/intake/test-batch" \
  "${ROOT}/raw" \
  "${ROOT}/raw/pdfs" \
  "${ROOT}/processed" \
  "${ROOT}/processed/text" \
  "${ROOT}/processed/chunks" \
  "${ROOT}/index" \
  "${ROOT}/index/lancedb" \
  "${ROOT}/state" \
  "${ROOT}/state/manifests" \
  "${ROOT}/state/logs" \
  "${ROOT}/state/failed" \
  "${ROOT}/state/model-cache" \
  "${ROOT}/vault" \
  "${VAULT_DIR}"
install -d -m 755 "${RUNTIME_DIR}"

echo "== Scaffolding Obsidian vault =="
install -d -m 755 \
  "${VAULT_DIR}/Attachments" \
  "${VAULT_DIR}/Daily" \
  "${VAULT_DIR}/Inbox" \
  "${VAULT_DIR}/Maps" \
  "${VAULT_DIR}/Sources" \
  "${VAULT_DIR}/Templates"

if [[ ! -f "${VAULT_DIR}/Home.md" ]]; then
  cat > "${VAULT_DIR}/Home.md" <<'EOF'
# HVE Knowledge Vault

## Entry points
- [[Inbox/Capture]]
- [[Maps/Knowledge Map]]
- [[Templates/Literature Note Template]]

## Operating model
- PDFs land in `/hve-library/intake/inbox/`
- Extracted text lands in `/hve-library/processed/text/`
- New PDFs are indexed automatically by the intake path unit
EOF
fi

if [[ ! -f "${VAULT_DIR}/Inbox/Capture.md" ]]; then
  cat > "${VAULT_DIR}/Inbox/Capture.md" <<'EOF'
# Capture

Drop quick notes here before they are organized into permanent knowledge notes.
EOF
fi

if [[ ! -f "${VAULT_DIR}/Maps/Knowledge Map.md" ]]; then
  cat > "${VAULT_DIR}/Maps/Knowledge Map.md" <<'EOF'
# Knowledge Map

## Current domains
- Bitcoin
- Sovereignty
- Treasury
- Health
- Family
EOF
fi

if [[ ! -f "${VAULT_DIR}/Templates/Literature Note Template.md" ]]; then
  cat > "${VAULT_DIR}/Templates/Literature Note Template.md" <<'EOF'
# Literature Note

## Source
- Title:
- Author:
- Location:

## Key ideas
- 

## Relevance to HVE
- 
EOF
fi

echo "== Installing Phase 1 packages =="
sudo apt-get update -qq
sudo apt-get install -y poppler-utils python3-venv

echo "== Installing knowledge-layer Python runtime =="
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  uv venv "${VENV_DIR}" --python /usr/bin/python3
fi
uv pip install --python "${VENV_DIR}/bin/python" \
  lancedb pyarrow numpy transformers torch sentencepiece safetensors

if [[ -x "${REPO_DIR}/scripts/bootstrap-obsidian.sh" ]]; then
  echo "== Installing native Obsidian desktop =="
  bash "${REPO_DIR}/scripts/bootstrap-obsidian.sh"
else
  echo "WARN bootstrap-obsidian.sh not present in this checkout — skipping Obsidian desktop bootstrap"
fi

echo "== Installing HVE intake user units =="
install -d -m 755 "${HOME}/.config/systemd/user"
install -m 644 "${REPO_DIR}/dotfiles/hve-intake.service" "${HOME}/.config/systemd/user/hve-intake.service"
install -m 644 "${REPO_DIR}/dotfiles/hve-intake.path" "${HOME}/.config/systemd/user/hve-intake.path"
systemctl --user daemon-reload
systemctl --user enable hve-intake.path
systemctl --user start hve-intake.path
systemctl --user status hve-intake.path --no-pager || true

cat <<'EOF'
Knowledge layer Phase 1 bootstrapped.

Sample PDF drop location:
  /hve-library/intake/inbox/

Enable/verify the intake watcher:
  systemctl --user daemon-reload
  systemctl --user enable hve-intake.path
  systemctl --user start hve-intake.path
  systemctl --user status hve-intake.path
EOF

if [[ -x "${REPO_DIR}/scripts/validate-knowledge-intake.sh" ]]; then
  bash "${REPO_DIR}/scripts/validate-knowledge-intake.sh" --root "${KNOWLEDGE_ROOT}"
else
  echo "WARN validate-knowledge-intake.sh not present in this checkout — skipping validation hook"
fi
