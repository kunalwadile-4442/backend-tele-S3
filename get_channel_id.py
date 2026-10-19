import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

api_id = os.getenv("TELEGRAM_API_ID", "").strip()
api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
session_path = os.getenv(
    "TELEGRAM_SESSION_PATH",
    str(BASE_DIR / "telegram_session"),
).strip()

if not api_id or not api_hash:
    raise SystemExit("Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in backend/.env")

# Use an absolute session path so the script and backend can share it.
session_path = str(Path(session_path).expanduser().resolve())


async def main():
    client = TelegramClient(session_path, int(api_id), api_hash)

    async with client:
        print("Telegram authentication successful.")
        print("Available channels:")

        async for dialog in client.iter_dialogs():
            if dialog.is_channel:
                print(f"Name: {dialog.name} | ID: {dialog.id}")


if __name__ == "__main__":
    asyncio.run(main())