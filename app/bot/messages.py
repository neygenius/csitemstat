import httpx
import logging
from typing import Optional

from app.utils.retry import retry_async

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

    async def _send():
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

    try:
        await retry_async(
            _send,
            retries=3,
            delay=2.0,
            exceptions=(httpx.ConnectTimeout, httpx.ReadTimeout, 
                        httpx.RemoteProtocolError, httpx.HTTPStatusError)
        )
    except Exception as e:
        logger.error(f"Failed to send message after retries: {e}", exc_info=True)


async def send_photo(
    bot_token: str, 
    chat_id: int, 
    photo_bytes: bytes, 
    caption: Optional[str] = None,
    reply_markup=None
) -> None:
    """
    Отправляет изображение с опциональной клавиатурой.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    data = {"chat_id": chat_id, "caption": caption}
    if caption is not None:
        data["caption"] = caption
    if reply_markup:
        data["reply_markup"] = reply_markup.model_dump_json()

    files = {"photo": ("chart.png", photo_bytes, "image/png")}

    async def _send():
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(url, data=data, files=files)

    try:
        await retry_async(
            _send,
            retries=3,
            delay=2.0,
            exceptions=(httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError)
        )
    except Exception as e:
        logger.error(f"Failed to send photo after retries: {e}", exc_info=True)