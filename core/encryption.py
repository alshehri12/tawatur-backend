"""
Symmetric encryption utilities using Fernet (AES-128-CBC + HMAC-SHA256).
Used to encrypt sensitive fields before storing in the database:
  - Phone numbers
  - National ID / Iqama numbers
  - IMEI numbers
  - Serial numbers

The encryption key is loaded from settings.ENCRYPTION_KEY (stored in .env).
"""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the project encryption key."""
    key = settings.ENCRYPTION_KEY
    # Accept both str and bytes — Fernet expects bytes
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt(plain_text: str) -> str:
    """
    Encrypt a plain-text string and return a URL-safe base64-encoded ciphertext.
    The output is safe to store in a CharField / TextField.
    """
    if not plain_text:
        return ''
    return _get_fernet().encrypt(plain_text.encode()).decode()


def decrypt(cipher_text: str) -> str:
    """
    Decrypt a ciphertext produced by encrypt(). Raises ValueError if the
    token is invalid or has been tampered with.
    """
    if not cipher_text:
        return ''
    try:
        return _get_fernet().decrypt(cipher_text.encode()).decode()
    except InvalidToken:
        raise ValueError('فشل فك التشفير: البيانات تالفة أو المفتاح غير صحيح.')
