"""
Business logic services for the accounts app.

Two services live here:
  - OTPService               : issue, verify, rate-limit, and lock OTPs.
  - IdentityVerificationService : mock Absher (individual) and Wathiq (business).

Services are called by views — they contain no HTTP logic and can be
unit-tested without a request context.
"""

import random
import hashlib
from datetime import timedelta

from django.utils import timezone
from django.core.cache import cache
from django.conf import settings


# ── OTP Service ───────────────────────────────────────────────────────────────

class OTPService:
    """
    Handles the full OTP lifecycle:
      request_otp()  → generates, stores (hashed), and returns the plain code.
      verify_otp()   → validates the supplied code, tracks attempts, enforces lockout.
    """

    # Redis cache key templates
    _RATE_LIMIT_KEY = 'otp:rate:{phone_hash}'   # counts requests per hour
    _LOCKOUT_KEY = 'otp:lock:{phone_hash}'       # set when max attempts exceeded

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _generate() -> str:
        """Return a cryptographically sufficient 6-digit OTP string."""
        return f'{random.SystemRandom().randint(0, 999999):06d}'

    @staticmethod
    def _hash_otp(otp: str) -> str:
        """SHA-256 hash of the plain OTP — this is what we store, never the OTP itself."""
        return hashlib.sha256(otp.encode()).hexdigest()

    # ── Public API ────────────────────────────────────────────────────────────

    @classmethod
    def is_locked_out(cls, phone_hash: str) -> bool:
        """True if this phone is currently blocked due to too many failed attempts."""
        return cache.get(cls._LOCKOUT_KEY.format(phone_hash=phone_hash)) is not None

    @classmethod
    def request_otp(cls, phone_number: str, purpose: str) -> tuple:
        """
        Generate and persist a new OTP for the given phone + purpose.

        Returns:
            (otp_plain: str, success: bool)
            otp_plain is None when rate-limited or locked out.

        Side effects:
            - Invalidates any previous unused OTPs for this phone+purpose.
            - Increments the hourly rate-limit counter in Redis.
        """
        from core.hashing import hash_phone
        from .models import OTPVerification

        phone_hash = hash_phone(phone_number)

        # Block if the user is locked out from too many wrong attempts
        if cls.is_locked_out(phone_hash):
            return None, False

        # Enforce hourly rate limit (default: 5 requests / hour)
        rate_key = cls._RATE_LIMIT_KEY.format(phone_hash=phone_hash)
        request_count = cache.get(rate_key, 0)
        if request_count >= settings.OTP_RATE_LIMIT_PER_HOUR:
            return None, False

        # Invalidate any existing pending OTPs to prevent replay
        OTPVerification.objects.filter(
            phone_hash=phone_hash,
            purpose=purpose,
            is_used=False,
        ).update(is_used=True)

        otp_plain = cls._generate()

        OTPVerification.objects.create(
            phone_hash=phone_hash,
            otp_hash=cls._hash_otp(otp_plain),
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
        )

        # Increment request counter; TTL = 1 hour
        cache.set(rate_key, request_count + 1, timeout=3600)

        return otp_plain, True

    @classmethod
    def verify_otp(cls, phone_number: str, otp: str, purpose: str) -> tuple:
        """
        Validate the user-supplied OTP against the most recent pending record.

        Returns:
            (success: bool, error_message: str | None)
        """
        from core.hashing import hash_phone
        from .models import OTPVerification

        phone_hash = hash_phone(phone_number)

        if cls.is_locked_out(phone_hash):
            return False, 'حسابك محظور مؤقتاً بسبب محاولات خاطئة متعددة. حاول مرة أخرى بعد ساعة.'

        # Fetch the latest valid (unused, non-expired) OTP record
        try:
            record = OTPVerification.objects.filter(
                phone_hash=phone_hash,
                purpose=purpose,
                is_used=False,
                expires_at__gt=timezone.now(),
            ).latest('created_at')
        except OTPVerification.DoesNotExist:
            return False, 'رمز التحقق غير صالح أو منتهي الصلاحية.'

        record.attempts += 1

        if record.otp_hash != cls._hash_otp(otp):
            remaining = settings.OTP_MAX_ATTEMPTS - record.attempts

            if remaining <= 0:
                # Max attempts reached — invalidate record and lock the phone
                record.is_used = True
                record.save()
                lockout_seconds = settings.OTP_LOCKOUT_HOURS * 3600
                cache.set(
                    cls._LOCKOUT_KEY.format(phone_hash=phone_hash),
                    True,
                    timeout=lockout_seconds,
                )
                return False, 'تم تجاوز الحد الأقصى للمحاولات. سيتم إلغاء الحظر بعد ساعة.'

            record.save()
            return False, f'رمز التحقق غير صحيح. المحاولات المتبقية: {remaining}'

        # Correct OTP — mark as used so it cannot be replayed
        record.is_used = True
        record.save()
        return True, None


# ── Identity Verification Service ─────────────────────────────────────────────

class IdentityVerificationService:
    """
    Mock implementation of Saudi government identity verification services.

    In production Phase 2, these methods will be replaced with real API calls:
      - verify_individual() → Absher (وزارة الداخلية)
      - verify_business()   → Wathiq / Mhrsd (وزارة الموارد البشرية)

    For MVP, we store hashed identifiers and mark the user as 'pending'
    (identity_submitted=True / cr_submitted=True).
    The admin can manually flip absher_verified / wathiq_verified once
    real integrations are ready.
    """

    @staticmethod
    def verify_individual(user, national_id: str = None, iqama: str = None,
                           full_name: str = None) -> tuple:
        """
        Submit individual identity data (mock Absher).

        Stores the HMAC hash of the supplied ID (for lookups) plus an
        encrypted, reversible copy (so it can be printed on a certificate/
        contract later) and marks identity_submitted=True.
        Returns (success: bool, error: str | None).
        """
        from core.hashing import hash_value
        from core.encryption import encrypt

        if not national_id and not iqama:
            return False, 'يجب إدخال رقم الهوية الوطنية أو رقم الإقامة.'

        update_fields = ['identity_submitted']

        if national_id:
            user.national_id_hash = hash_value(national_id.strip())
            user.national_id_encrypted = encrypt(national_id.strip())
            update_fields += ['national_id_hash', 'national_id_encrypted']

        if iqama:
            user.iqama_hash = hash_value(iqama.strip())
            user.iqama_encrypted = encrypt(iqama.strip())
            update_fields += ['iqama_hash', 'iqama_encrypted']

        if full_name:
            user.full_name = full_name.strip()
            update_fields.append('full_name')

        user.identity_submitted = True
        user.save(update_fields=update_fields)

        return True, None

    @staticmethod
    def verify_business(user, cr_number: str, business_name: str) -> tuple:
        """
        Submit business registration data (mock Wathiq).

        Stores the HMAC hash of the CR number and marks cr_submitted=True.
        Returns (success: bool, error: str | None).
        """
        from core.hashing import hash_value

        if not cr_number:
            return False, 'يجب إدخال رقم السجل التجاري.'
        if not business_name:
            return False, 'يجب إدخال اسم المنشأة.'

        user.cr_number_hash = hash_value(cr_number.strip())
        user.business_name = business_name.strip()
        user.cr_submitted = True
        user.save(update_fields=['cr_number_hash', 'business_name', 'cr_submitted'])

        return True, None
