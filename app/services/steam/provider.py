import logging
from typing import Any

import httpx
from aiohttp import ClientError
from aiosteampy.client import App, AppContext, Currency, SteamClient, SteamPublicClient
from aiosteampy.exceptions import SteamError
from aiosteampy.id import SteamID
from aiosteampy.session import SteamSession
from aiosteampy.transport.exceptions import NetworkError, TransportError

from app.services.steam.interface import ISteamProvider
from app.services.steam.session_manager import SessionManager
from app.utils.retry import retry_async

logger = logging.getLogger(__name__)


class SteamProvider(ISteamProvider):
    """
    Реализация ISteamProvider на основе aiosteampy.
    """

    def __init__(self, session_manager: SessionManager):
        self._session_manager = session_manager
        self._session: SteamSession | None = None
        self._client: SteamClient | None = None
        self._public_client: SteamPublicClient | None = None
        self._fallback_country = "RU"
        self._fallback_currency = 5

    async def _get_price_overview_fallback(
        self, app_id: int, market_hash_name: str
    ) -> dict[str, Any]:
        """
        Прямой запрос к Steam Web API для получения цены (на случай ошибки aiosteampy).
        """
        url = "https://steamcommunity.com/market/priceoverview/"
        params = {
            "appid": app_id,
            "country": self._fallback_country,
            "currency": self._fallback_currency,
            "market_hash_name": market_hash_name,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return {"success": False}
            data = resp.json()
            if not data.get("success", False):
                return {"success": False}
            lowest = data.get("lowest_price", "0")
            median = data.get("median_price", "0")
            volume = data.get("volume", "0")
            return {
                "success": True,
                "lowest_price": lowest,
                "median_price": median,
                "volume": volume,
            }

    async def initialize(self) -> None:
        self._session = await self._session_manager.get_session()
        self._client = SteamClient(session=self._session)
        self._public_client = SteamPublicClient(country="RU", currency=Currency.RUB)
        logger.info("SteamProvider initialized")

    async def ensure_authenticated(self) -> bool:
        if self._session and self._session.cookies_are_valid:
            logger.debug("Session cookies are valid")
            return True

        if self._session is not None:
            logger.warning("Session cookies invalid, attempting refresh...")
            try:
                await self._session.refresh_access_token()
                await self._session.obtain_cookies()
                if self._session.cookies_are_valid:
                    logger.info("Session refreshed successfully")
                    return True
            except (TransportError, SteamError) as e:
                logger.warning(f"Refresh failed: {e}, re-creating session...")

        logger.info("Creating new Steam session...")
        try:
            await self._session_manager._create_new_session()
            self._session = await self._session_manager.get_session()
            self._client = SteamClient(session=self._session)
            self._public_client = SteamPublicClient(country="RU", currency=Currency.RUB)
            return True
        except (TransportError, SteamError):
            logger.exception("Failed to ensure authentication")
            return False

    async def get_price_overview(
        self, app_id: int, market_hash_name: str
    ) -> dict[str, Any]:
        try:

            async def _fetch():
                return await self._public_client.market.get_price_overview(
                    market_hash_name, App(app_id)
                )

            overview = await retry_async(
                _fetch,
                retries=3,
                delay=2.0,
                exceptions=(ClientError, TimeoutError, ConnectionError, NetworkError),
            )

            if not overview:
                return {"success": False}

            return {
                "success": True,
                "lowest_price": f"{overview.lowest_price / 100:.2f}"
                if overview.lowest_price is not None
                else "0.00",
                "median_price": f"{overview.median_price / 100:.2f}"
                if overview.median_price is not None
                else "0.00",
                "volume": str(overview.volume),
            }
        except KeyError:
            logger.warning(
                f"aiosteampy failed to parse price overview, using fallback for {market_hash_name}"
            )
            return await self._get_price_overview_fallback(app_id, market_hash_name)

        except Exception:
            logger.exception(f"Price overview error for {market_hash_name}")
            return {"success": False}

    async def get_price_history(self, app_id: int, market_hash_name: str) -> list[list]:
        if not await self.ensure_authenticated():
            logger.exception(
                f"Authentication failed for fetch {market_hash_name} history"
            )
            return []

        try:

            async def _fetch():
                return await self._client.market.get_price_history(
                    market_hash_name, App(app_id)
                )

            history = await retry_async(
                _fetch,
                retries=3,
                delay=2.0,
                exceptions=(ClientError, TimeoutError, ConnectionError, NetworkError),
            )

            return [
                [
                    entry.date.strftime("%b %d %Y %H: +0"),
                    entry.price_raw,
                    str(entry.daily_volume),
                ]
                for entry in history
            ]
        except Exception:
            logger.exception(f"Price history error for {market_hash_name}")
            return []

    async def get_inventory(self, steam_id64: int, app_id: int) -> dict[str, Any]:
        if not await self.ensure_authenticated():
            logger.exception(f"Authentication failed for fetch inventory {steam_id64}")
            return {"success": False}

        try:
            user_id = SteamID(steam_id64)

            async def _fetch():
                return await self._client.inventory.get_user_inventory(
                    user_id, AppContext(App(app_id), 2)
                )

            inventory_response = await retry_async(
                _fetch,
                retries=3,
                delay=2.0,
                exceptions=(ClientError, TimeoutError, ConnectionError, NetworkError),
            )

            items = inventory_response.items
            if not items:
                logger.warning("Inventory is empty")
                return {"success": True, "rgInventory": {}, "rgDescriptions": {}}

            assets = {}
            descriptions = {}

            for item in items:
                try:
                    asset_id = str(item.asset_id)
                    class_id = str(item.description.class_id)
                    instance_id = str(item.description.instance_id or 0)
                    market_hash_name = item.description.market_hash_name

                    assets[asset_id] = {
                        "classid": class_id,
                        "instanceid": instance_id,
                    }
                    descriptions[f"{class_id}_{instance_id}"] = {
                        "market_hash_name": market_hash_name,
                    }
                except Exception:
                    logger.exception(f"Error processing item {item}")
                    raise

            return {
                "success": True,
                "rgInventory": assets,
                "rgDescriptions": descriptions,
            }
        except Exception:
            logger.exception(f"Inventory error for {steam_id64} after retries")
            return {"success": False}

    async def close(self) -> None:
        if self._client:
            await self._client.transport.close()

        if self._public_client:
            await self._public_client.transport.close()

        if self._session:
            await self._session_manager.close()
