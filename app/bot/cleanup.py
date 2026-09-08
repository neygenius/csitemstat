import logging

import redis.asyncio as redis
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError

logger = logging.getLogger(__name__)

CATEGORY_TEMP = "temporary"


class CleanupManager:
    """
    Управляет удалением устаревших сообщений.
    """

    def __init__(self, redis_client: redis.Redis = None):
        self.redis = redis_client

    async def register_message(
        self, chat_id: int, message_id: int, category: str
    ) -> None:
        """
        Добавляет message_id в список для категории.
        """
        key = self._key(chat_id, category)
        await self.redis.rpush(key, message_id)

    async def clear_messages(self, chat_id: int, category: str, bot: Bot) -> None:
        """
        Удаляет все сообщения категории и очищает список.
        """
        key = self._key(chat_id, category)
        message_ids = await self.redis.lrange(key, 0, -1)
        if not message_ids:
            return

        for mid in message_ids:
            try:
                await bot.delete_message(chat_id, int(mid))
            except (TelegramAPIError, TelegramNetworkError) as e:
                logger.debug(f"Failed to delete message {mid}: {e}")
        await self.redis.delete(key)

    async def replace_message(
        self, chat_id: int, message_id: int, category: str, bot: Bot
    ) -> None:
        """
        Удаляет старые, регистрирует новое.
        """
        await self.clear_messages(chat_id, category, bot)
        await self.register_message(chat_id, message_id, category)

    def _key(self, chat_id: int, category: str) -> str:
        return f"cleanup:{chat_id}:{category}"
