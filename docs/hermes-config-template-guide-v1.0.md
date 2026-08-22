# Hermes YAML Configuration Guide

This guide explains `config/hermes-config.template.yaml` in plain English.
The YAML file is a starting configuration for Hermes. It tells Hermes which
model to use, which tools are available, how long tasks may run, and what
safety rules apply.

## Before editing

Make a backup of the active configuration before changing it. Keep secrets out
of Git. Values such as `${HVE_MCP_API_KEY}` are environment-variable
references; they are intentionally not replaced with real keys in this file.

## Main sections

### `agent`

These are the general limits for an agent run:

- `default_model` is the main model name used by Hermes.
- `max_turns` limits how many tool-and-answer cycles one request may use.
- `gateway_timeout` is the maximum time allowed for a request.
- `gateway_timeout_warning` controls when Hermes warns that a request is taking
  too long.
- `gateway_notify_interval` controls how often progress notifications appear.
- `reasoning_effort` selects the normal reasoning level.
- `api_max_retries` controls retries after provider errors.

The template uses Qwen3.8 locally, a 30-turn limit, and a 600-second timeout
to prevent simple requests from spinning indefinitely.

### `model`, `providers`, and `fallback_providers`

`model` selects the active provider and model. `providers` defines the
OpenAI-compatible endpoints Hermes can call. The local Ollama provider lists
the approved Qwen3.8, Qwen2.5, and Nomic models.

`fallback_providers` can define alternate providers if the local model is
unavailable. Keep fallback entries empty or explicitly configured if local-only
operation is required.

### `platform_toolsets`

This section decides which tools each channel can use. The WhatsApp entry
enables browser and web research, files, memory, session search, terminal,
code execution, delegation, cron, todos, computer use, and media tools.

Only give powerful tools to trusted channels. A group should not receive the
same privileges as an allowlisted private control channel.

### `whatsapp`, `telegram`, `discord`, and `slack`

These sections control channel behavior, such as whether a user or group is
allowed, whether a mention is required, and whether streaming is enabled.
Channel access policy is separate from tool access policy: both must be
configured correctly.

### `approvals`

Approval settings add human confirmation before sensitive actions:

- `mode: auto` allows routine approved work without prompting every time.
- `destructive_slash_confirm: true` protects commands that discard session
  state, such as `/clear`, `/new`, `/reset`, and `/undo`.
- `cron_mode: deny` prevents cron actions unless the policy explicitly allows
  them.
- `mcp_reload_confirm: true` requires confirmation before reloading MCP
  services.

Do not disable destructive confirmations just to make a workflow faster.

### `terminal` and `code_execution`

`terminal` controls local command execution, including its timeout, working
directory, and optional container settings. `code_execution` limits project
code runs and their duration.

These tools can change files or system state. Use them only for trusted users,
keep command allowlists narrow, and preserve the security settings unless
there is a documented reason to change them.

### `memory` and `honcho`

`memory` controls durable user memory, profile information, and memory size
limits. The configured provider is Honcho. Memory helps Hermes retain useful
context without carrying an unlimited conversation transcript into every
request.

### `mcp_servers`

MCP servers add external tools to Hermes. Each server has a command or URL,
an enabled flag, and optionally a tool filter. Disable a server that is
unnecessary or repeatedly failing; otherwise it may waste time reconnecting
and make simple requests slow.

Never commit API keys or private credentials in this section.

### `tool_loop_guardrails`

These settings detect repeated failures or no-progress loops. With
`hard_stop_enabled: true`, Hermes stops instead of continuing forever after
repeated tool failures.

This is an important protection for messaging channels, where a user may not
be watching the agent continuously.

### `streaming`, `display`, and `logging`

These sections control how progress and responses are shown. Streaming can
make WhatsApp feel responsive. Reasoning display should remain disabled for
the executive channel, even when the model uses internal reasoning.
`logging` controls log level, size, and backup retention.

### `security`

Security settings control private-URL access, secret redaction, and request
filtering. Keep secret redaction enabled and do not allow private URLs unless
the network boundary is understood.

## Safe change workflow

1. Edit only the section related to the requested behavior.
2. Parse the YAML before restarting Hermes.
3. Review the diff and confirm no secrets were added.
4. Restart the affected service only.
5. Check the service status and logs.
6. Test a simple request before testing powerful tools.

The companion `docs/whatsapp-channel-policy-v1.0.md` records the intended
WhatsApp behavior and safety boundaries for the current HVE deployment.
