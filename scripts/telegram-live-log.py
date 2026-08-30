#!/usr/bin/env python3
"""
Hermes Telegram Live Log Watcher
Polls ~/.hermes/state.db for new Telegram messages and appends them to
~/hanshermesagent/logs/telegram/live.log in real time.

Run: python3 ~/hanshermesagent/scripts/telegram-live-log.py
Or via systemd: systemctl --user start hermes-telegram-log
"""

import sqlite3
import time
import datetime
import os
import sys
import signal

STATE_DB = os.path.expanduser("~/.hermes/state.db")
LOG_FILE = os.path.expanduser("~/hanshermesagent/logs/telegram/live.log")
POLL_INTERVAL = 3  # seconds
WATERMARK_FILE = os.path.expanduser("~/.hermes/telegram_log_watermark")

running = True

def handle_signal(signum, frame):
    global running
    running = False

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)


def load_watermark():
    if os.path.exists(WATERMARK_FILE):
        try:
            return int(open(WATERMARK_FILE).read().strip())
        except Exception:
            pass
    return 0


def save_watermark(msg_id):
    with open(WATERMARK_FILE, "w") as f:
        f.write(str(msg_id))


def format_timestamp(ts):
    if ts is None:
        return "??:??:??"
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def get_new_messages(conn, since_id):
    rows = conn.execute("""
        SELECT m.id, m.role, m.content, m.timestamp, m.tool_name, s.source, s.title
        FROM messages m
        JOIN sessions s ON m.session_id = s.id
        WHERE s.source = 'telegram'
          AND m.id > ?
          AND m.role IN ('user', 'assistant')
          AND m.content IS NOT NULL
          AND trim(m.content) != ''
        ORDER BY m.id ASC
    """, (since_id,)).fetchall()
    return rows


def append_to_log(lines):
    with open(LOG_FILE, "a") as f:
        for line in lines:
            f.write(line + "\n")
    # Also print to stdout so journalctl picks it up
    for line in lines:
        print(line, flush=True)


def main():
    last_id = load_watermark()
    append_to_log([
        "",
        f"{'='*70}",
        f"  Hermes Telegram Log Watcher started — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Watching: {STATE_DB}",
        f"  Starting from message ID: {last_id}",
        f"{'='*70}",
    ])

    while running:
        try:
            conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True,
                                   check_same_thread=False)
            rows = get_new_messages(conn, last_id)
            conn.close()

            if rows:
                lines = []
                for row in rows:
                    msg_id, role, content, ts, tool_name, source, title = row
                    ts_str = format_timestamp(ts)
                    label = "HANS   " if role == "user" else "HERMES "
                    # Truncate very long assistant messages (tool outputs etc)
                    text = content.strip()
                    if len(text) > 2000:
                        text = text[:2000] + "\n  [... truncated ...]"
                    lines.append(f"[{ts_str}] {label} | {text}")
                    lines.append("")  # blank line between messages
                    last_id = max(last_id, msg_id)

                append_to_log(lines)
                save_watermark(last_id)

        except Exception as e:
            # DB may be locked briefly — just retry
            pass

        time.sleep(POLL_INTERVAL)

    append_to_log([f"[{datetime.datetime.now()}] Watcher stopped."])


if __name__ == "__main__":
    main()
