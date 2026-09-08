from cryptography.fernet import Fernet

from app.config import settings


fernet = Fernet(settings.FERNET_KEY.encode())

def encrypt_steam_id(steam_id64: int) -> bytes:
    return fernet.encrypt(str(steam_id64).encode())

def decrypt_steam_id(encrypted: bytes) -> int:
    return int(fernet.decrypt(encrypted).decode())