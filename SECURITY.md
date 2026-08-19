# Security Policy — hermes-cfo

## What this repo contains

This repository holds **configuration templates, scripts, agent definitions, and documentation** for the Hermes CFO system. It is a **public repo** hosted under the `humanvalueexchange` GitHub org.

**No live secrets should ever be committed here.**

---

## Secret Hygiene Rules

### Never commit
| Type | Example |
|---|---|
| MCP API keys | `X-HVE-API-Key` values |
| `.env` files with real values | `~/.hermes-mcp.env`, `~/.hermes/profiles/main/.env` |
| Live `config.yaml` | `~/.hermes/profiles/main/config.yaml` (contains API key header) |
| SSH private keys | `id_rsa`, `id_ed25519` |
| Tailscale / VPN configs | `wg0.conf`, etc. |
| LAN or Tailscale IPs | Use `[DGX_LAN_IP]` / `[DGX_TAILSCALE_IP]` placeholders |

### Always use templates
| Template (commit this ✅) | Live file (never commit ❌) |
|---|---|
| `config/hermes-config.template.yaml` | `~/.hermes/profiles/main/config.yaml` |
| `config/hermes-env.template` | `~/.hermes-mcp.env` |
| `dotfiles/SOUL.md` | `~/.hermes/profiles/main/SOUL.md` |

### IP / hostname placeholders
| Placeholder | Meaning |
|---|---|
| `[DGX_LAN_IP]` | DGX Spark LAN IP (static, private) |
| `[DGX_TAILSCALE_IP]` | DGX Spark Tailscale IP |
| `[MERCURY_LAN_IP]` | Mercury Pi LAN IP |

---

## If a Secret Is Accidentally Committed

1. **Rotate immediately** — treat the secret as compromised the moment it touches any git commit, even before pushing.
2. Rewrite history (`git filter-repo` or BFG) if the commit has NOT been pushed to GitHub.
3. If already pushed to a public repo, rotation is the only safe option — history rewrites cannot guarantee the secret was not scraped.
4. Open a private issue or DM `@HansHWestphal` immediately.

> **Note:** An MCP API key was exposed in commit history in May 2026. It was
> rotated and revoked immediately; no key value is reproduced here.

---

## Reporting a Vulnerability

This is an internal company repo. Report security issues directly to:

**Hans Westphal (CEO)** — via WhatsApp direct message or Telegram.

Do not open a public GitHub issue for active security vulnerabilities.
