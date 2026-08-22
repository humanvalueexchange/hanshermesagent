# Hermes WhatsApp Channel Policy

Effective 2026-08-22 for the Hans allowlisted WhatsApp DM.

## Purpose

WhatsApp is the local Qwen3.8 executive control channel for HVE operations,
knowledge work, memory, research, coding, and approved system automation.

## Model stack

- `qwen3.8:27b`: Hermes primary
- `qwen3.8-distill-2b:q4_k_m`: Honcho deriver and summaries
- `nomic-embed-text:latest`: embeddings

All three are preloaded through `hermes-model-preload.service` with
`keep_alive=-1`. Qwen3.5 and GPT-OSS remain installed only as fallback models.

## WhatsApp capabilities

The allowlisted Hans DM has browser/web, vision, file, skills, Honcho memory,
session search, terminal, code execution, delegation, coder dispatch, cron,
todo, computer use, image generation, BFL, TTS, and clarification capabilities.

## Safety boundaries

- Destructive slash commands require confirmation.
- Computer-use and destructive system actions remain confirmation-gated.
- Groups require an explicit mention and should be separately allowlisted before
  receiving operational control.
- The link collector MCP server is disabled to prevent repeated failed
  reconnection attempts.
- The tool-loop hard stop is enabled.

## Responsiveness policy

- Gateway timeout: 600 seconds
- Warning interval: 120 seconds
- Timeout warning: 300 seconds
- Maximum agent turns: 30
- WhatsApp streaming: enabled
- Reasoning display: disabled

Simple factual questions and memory updates should use direct answering with
bounded output. Extended reasoning, web research, coding, and system operations
may use the full tool surface when explicitly justified.
