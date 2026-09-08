import pytest
from unittest.mock import MagicMock
from app.services.steam.factory import create_steam_provider
import app.services.steam.provider as provider_module

def test_create_steam_provider_aiosteampy(monkeypatch):
    monkeypatch.setattr('app.services.steam.factory.settings.STEAM_AUTH_MODE', 'aiosteampy')
    monkeypatch.setattr(provider_module, 'SteamPublicClient', MagicMock())
    provider = create_steam_provider()
    assert isinstance(provider, provider_module.SteamProvider)

def test_create_steam_provider_invalid_mode(monkeypatch):
    monkeypatch.setattr('app.services.steam.factory.settings.STEAM_AUTH_MODE', 'invalid')
    assert create_steam_provider() is None