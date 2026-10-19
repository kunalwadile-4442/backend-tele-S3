"""Run once in a trusted terminal to authorize the backend's MTProto session."""
import asyncio
from telethon import TelegramClient
from app.core.config import settings

async def main():
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH first")
    client = TelegramClient(settings.telegram_session_path, settings.telegram_api_id, settings.telegram_api_hash)
    await client.start()
    print("Telegram session authorized. Keep this session file private.")
    await client.disconnect()

if __name__ == "__main__": asyncio.run(main())
