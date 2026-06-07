"""
Deterministic hashing utilities for sensitive identifiers.

We store two representations of sensitive values in the database:
  1. Encrypted value  — for when we need to display/read back the original (e.g. phone).
  2. HMAC-SHA256 hash — for database lookups (unique constraints, indexes).

Using HMAC (keyed hash) instead of plain SHA-256 prevents offline rainbow-table
attacks: without the SECRET_KEY, an attacker with DB access cannot reverse-lookup
a hash to its original value.
"""

import hmac
import hashlib
from django.conf import settings


def _hmac_sha256(value: str) -> str:
    """Return HMAC-SHA256 hex digest of value, keyed with Django's SECRET_KEY."""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()


def hash_value(value: str) -> str:
    """Generic HMAC hash for any sensitive string (national ID, IMEI, serial, etc.)."""
    if not value:
        return ''
    return _hmac_sha256(value.strip())


def normalize_phone(phone: str) -> str:
    """
    Normalize a Saudi phone number to the canonical +9665XXXXXXXX format.
    Accepts: 05XXXXXXXX  /  9665XXXXXXXX  /  +9665XXXXXXXX
    """
    phone = phone.replace(' ', '').replace('-', '')
    if phone.startswith('05'):
        phone = '+966' + phone[1:]          # 05X → +9665X
    elif phone.startswith('9665'):
        phone = '+' + phone                 # 9665X → +9665X
    return phone


def hash_phone(phone_number: str) -> str:
    """Return the canonical HMAC hash of a Saudi phone number."""
    return _hmac_sha256(normalize_phone(phone_number))
