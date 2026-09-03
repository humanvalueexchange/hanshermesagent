# Hermes Reliability Event Monitoring

The Spark watcher stores normalized findings in the profile-local SQLite
database:

`~/.hermes/profiles/hanshermesagent/workspace/spark-health-watchdog/reliability.db`

The database contains event summaries, bounded occurrences, and an idempotent
weekly review ledger. Details are bounded and redact credentials, tokens,
cookies, and sensitive URL query values. SQLite writes use one transaction per
watcher cycle; a failed write exits the watcher non-zero rather than reporting
healthy.

## Alert policy

The default `suppress_advisories` mode stores short-lived findings without
WhatsApp output. User-impacting channel disconnects and recorded delivery
failures alert immediately. Other actionable findings alert after three
occurrences or one hour of continuous activity. The thresholds are
configurable:

```text
HVE_WATCHDOG_TRIAGE_MODE=legacy|shadow|suppress_advisories
HVE_WATCHDOG_ESCALATE_OCCURRENCES=3
HVE_WATCHDOG_ESCALATE_AFTER_SECONDS=3600
HVE_RELIABILITY_OCCURRENCE_RETENTION_DAYS=90
HVE_RELIABILITY_DB=/path/to/reliability.db
```

Set `HVE_WATCHDOG_TRIAGE_MODE=legacy` to roll back to the prior alert
transitions while retaining the SQLite evidence. `shadow` also preserves the
prior WhatsApp output while exercising the store.

## Weekly review

`hve-weekly-reliability-review` is a Hermes no-agent job scheduled for Monday
morning. It reads the preceding Monday-Sunday period, ranks a bounded queue,
and writes review decisions and next-review dates. It never restarts services,
changes network configuration, or mutates production state. Empty or
non-material reviews produce no WhatsApp message.
