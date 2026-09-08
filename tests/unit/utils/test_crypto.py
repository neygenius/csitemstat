import pytest
from app.utils.crypto import encrypt_steam_id, decrypt_steam_id

def test_encrypt_decrypt_roundtrip():
    steam_id = 76561198000000000
    encrypted = encrypt_steam_id(steam_id)
    assert encrypted != steam_id
    decrypted = decrypt_steam_id(encrypted)
    assert decrypted == steam_id

def test_decrypt_invalid():
    with pytest.raises(Exception):
        decrypt_steam_id(b"invalid")