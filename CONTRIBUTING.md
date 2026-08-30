# HVE Dev Loop Protocol

## Workflow

All work flows through GitHub Issues and PRs. No side channels.

```
Claude (CTO)  → Issue comment with spec  →  @Vulcan
Vulcan        → PR + comment with results →  @Grok
Grok          → Validation comment        →  @Claude "approve to deploy"
Claude        → Merge + deploy + close Issue
```

## DGX Spark

Access details are shared privately with authorized team members only. Contact Hans directly.

| | |
|---|---|
| SSH | `ssh hans@[DGX_TAILSCALE_IP]` |
| Ollama | `http://[DGX_TAILSCALE_IP]:11434` |
| MCP | `ws://[DGX_TAILSCALE_IP]:8765` |
| Acceptance gate | `bash ~/hanshermesagent/scripts/test-tool-enforcement.sh` |
| Deploy | `systemctl --user restart hermes-gateway.service` |
| Logs | `journalctl --user -u hermes-gateway.service -f` |

## Handoff trigger phrases

| Phrase | Who acts |
|---|---|
| `@Vulcan — your turn` | Vulcan implements |
| `@Grok — PR [link] ready. Run validation.` | Grok validates |
| `@Claude — approve to deploy` | Claude merges + deploys |
