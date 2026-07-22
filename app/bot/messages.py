import httpx
import logging

logger = logging.getLogger(__name__)

async def send_telegram_message(bot_token: str, chat_id: int, text: str, reply_markup=None):
    """
    Отправляет сообщение через Telegram Bot API
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

async def send_photo(bot_token: str, chat_id: int, photo_bytes: bytes, caption: str = None):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    files = {"photo": photo_bytes}
    data = {"chat_id": chat_id, "caption": caption}
    async with httpx.AsyncClient() as client:
        await client.post(url, data=data, files=files)
