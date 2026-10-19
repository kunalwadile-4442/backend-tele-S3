import asyncio
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from app.core.config import settings
from app.storage.base import StorageProvider

class TelegramStorageProvider(StorageProvider):
    """MTProto user session adapter. Telegram session stays backend-side."""
    def __init__(self): self.client = None; self.lock = asyncio.Lock()
    async def _client(self):
        if not settings.telegram_api_id or not settings.telegram_api_hash or not settings.telegram_storage_channel_id:
            raise RuntimeError("Telegram storage is not configured")
        async with self.lock:
            if self.client is None:
                self.client = TelegramClient(settings.telegram_session_path, settings.telegram_api_id, settings.telegram_api_hash)
                await self.client.connect()
                if not await self.client.is_user_authorized():
                    await self.client.disconnect(); self.client = None
                    raise RuntimeError("Telegram user session is not authorized")
        return self.client
    async def upload_file(self, stream, filename, mime_type, caption=None):
        client = await self._client()
        for attempt in range(3):
            try:
                message = await asyncio.wait_for(
                    client.send_file(
                        settings.telegram_storage_channel_id,
                        stream,
                        file_name=filename,
                        mime_type=mime_type,
                        caption=caption,
                        force_document=True,
                    ),
                    timeout=settings.upload_timeout_seconds,
                )
                return str(message.id)
            except FloodWaitError as exc:
                if attempt == 2 or exc.seconds > 60: raise RuntimeError("Telegram rate limit; retry later") from exc
                await asyncio.sleep(exc.seconds)
        raise RuntimeError("Telegram upload failed")
    async def download_file(self, reference):
        client = await self._client()
        message = await client.get_messages(settings.telegram_storage_channel_id, ids=int(reference))
        if not message or not message.media: raise FileNotFoundError("Stored media not found")
        async def chunks():
            async for chunk in client.iter_download(message.media, request_size=512 * 1024):
                yield chunk
        return chunks()
    async def delete_file(self, reference):
        client = await self._client()
        await client.delete_messages(settings.telegram_storage_channel_id, [int(reference)])
    async def check_health(self):
        try: return await (await self._client()).is_user_authorized()
        except Exception: return False
