"""Send a message to the Fantasy Baseball Telegram chat.

Used by the CCR scheduled agent (which can't access the local Telegram MCP)
to deliver the morning report. Reads credentials from environment variables.

Required env vars:
    TELEGRAM_API_ID
    TELEGRAM_API_HASH
    TELEGRAM_SESSION_STRING
    TELEGRAM_CHAT_ID  — numeric ID of the target chat/channel

Usage:
    echo "Your report here" | python -m waiver_agent.notify
    python -m waiver_agent.notify --message "Your report here"
    python -m waiver_agent.notify  # reads from stdin
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def _send(message: str) -> None:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    session_string = os.environ.get("TELEGRAM_SESSION_STRING")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    missing = [
        name for name, val in [
            ("TELEGRAM_API_ID", api_id),
            ("TELEGRAM_API_HASH", api_hash),
            ("TELEGRAM_SESSION_STRING", session_string),
            ("TELEGRAM_CHAT_ID", chat_id),
        ] if not val
    ]
    if missing:
        print(f"ERROR: Missing env vars: {missing}", file=sys.stderr)
        sys.exit(1)

    # Telegram has a 4096-char message limit — split if needed
    chunks = [message[i:i+4000] for i in range(0, len(message), 4000)]

    async with TelegramClient(StringSession(session_string), int(api_id), api_hash) as client:
        target = int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id
        for chunk in chunks:
            await client.send_message(target, chunk)
    print(f"Sent {len(chunks)} message(s) to chat {chat_id}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send morning report to Telegram")
    parser.add_argument("--message", "-m", help="Message text (reads stdin if omitted)")
    args = parser.parse_args()

    if args.message:
        message = args.message
    else:
        message = sys.stdin.read().strip()

    if not message:
        print("Nothing to send.", file=sys.stderr)
        sys.exit(0)

    asyncio.run(_send(message))


if __name__ == "__main__":
    main()
