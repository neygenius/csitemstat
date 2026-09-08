import pytest
from cryptography.fernet import InvalidToken

from app.utils.crypto import decrypt_steam_id, encrypt_steam_id


def test_encrypt_decrypt_roundtrip():
    steam_id = 76561198000000000
    encrypted = encrypt_steam_id(steam_id)
    assert encrypted != steam_id
    decrypted = decrypt_steam_id(encrypted)
    assert decrypted == steam_id


def test_decrypt_invalid():
    with pytest.raises(InvalidToken):
        decrypt_steam_id(b"invalid")
