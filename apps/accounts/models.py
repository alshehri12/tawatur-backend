"""
Accounts models:
  - User       : the platform's custom user (individual or business), phone-based auth.
  - OTPVerification : short-lived one-time-password records stored server-side.
"""

import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """
    Central user model for تواتر.

    Authentication is phone + OTP only — no email, no username, no password
    for regular users. The phone number is:
      - Stored encrypted (phone_number_encrypted) for when we need to read it back.
      - Stored as an HMAC hash (phone_hash) for unique lookups and the USERNAME_FIELD.

    Two account types share this model:
      - individual : Saudi nationals / residents (verified via Absher mock).
      - business   : Registered businesses (verified via Wathiq mock).
    """

    # ── Account type choices ──────────────────────────────────────────────────
    INDIVIDUAL = 'individual'
    BUSINESS = 'business'
    USER_TYPE_CHOICES = [
        (INDIVIDUAL, 'فرد'),
        (BUSINESS, 'جهة تجارية'),
    ]

    # ── Primary key ───────────────────────────────────────────────────────────
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── Phone number (the only identifier) ───────────────────────────────────
    # Encrypted copy — used when we need to display or send the number.
    phone_number_encrypted = models.TextField()
    # HMAC-SHA256 hash — used as the login identifier and for DB uniqueness.
    phone_hash = models.CharField(max_length=64, unique=True, db_index=True)

    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES)

    # ── Individual verification fields ────────────────────────────────────────
    # Hashed with HMAC so the original ID is never stored in plain text.
    national_id_hash = models.CharField(max_length=64, null=True, blank=True)
    iqama_hash = models.CharField(max_length=64, null=True, blank=True)
    # True once the user has submitted their ID (mock Absher step).
    identity_submitted = models.BooleanField(default=False)
    # Will become True when real Absher integration is live.
    absher_verified = models.BooleanField(default=False)
    absher_verified_at = models.DateTimeField(null=True, blank=True)

    # ── Business verification fields ──────────────────────────────────────────
    cr_number_hash = models.CharField(max_length=64, null=True, blank=True)
    business_name = models.CharField(max_length=255, null=True, blank=True)
    # True once the business has submitted its CR number (mock Wathiq step).
    cr_submitted = models.BooleanField(default=False)
    # Will become True when real Wathiq integration is live.
    wathiq_verified = models.BooleanField(default=False)

    # ── Security ──────────────────────────────────────────────────────────────
    # Hashed User-Agent + IP — logged on every login to detect anomalies.
    device_fingerprint_hash = models.CharField(max_length=64, null=True, blank=True)

    # ── Standard Django auth flags ────────────────────────────────────────────
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    # phone_hash is the login identifier — it is unique and deterministic.
    USERNAME_FIELD = 'phone_hash'
    REQUIRED_FIELDS = ['user_type']

    objects = UserManager()

    class Meta:
        db_table = 'accounts_user'
        verbose_name = 'مستخدم'
        verbose_name_plural = 'المستخدمون'

    def __str__(self):
        label = self.business_name or f'مستخدم ({self.user_type})'
        return f'{label} — {self.id}'

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def phone_number(self) -> str:
        """Decrypt and return the plain phone number."""
        from core.encryption import decrypt
        return decrypt(self.phone_number_encrypted)

    @property
    def can_transact(self) -> bool:
        """
        A user must submit verification before creating or approving transactions.
        Individuals need identity_submitted; businesses need cr_submitted.
        """
        if self.user_type == self.INDIVIDUAL:
            return self.identity_submitted
        return self.cr_submitted

    @property
    def verification_status(self) -> str:
        """
        Returns one of: 'unverified' | 'pending' | 'verified'
        'pending'  = submitted to mock service, awaiting real Absher/Wathiq.
        'verified' = real government verification confirmed (post-MVP).
        """
        if self.user_type == self.INDIVIDUAL:
            if self.absher_verified:
                return 'verified'
            if self.identity_submitted:
                return 'pending'
        else:
            if self.wathiq_verified:
                return 'verified'
            if self.cr_submitted:
                return 'pending'
        return 'unverified'


class OTPVerification(models.Model):
    """
    Server-side record of an issued OTP.

    The OTP itself is never stored in plain text — only its HMAC-SHA256 hash.
    On verification, we hash the user-supplied code and compare hashes.

    One valid (unused, non-expired) record may exist per phone+purpose at a time;
    OTPService invalidates older records before issuing a new one.
    """

    # ── Purpose choices ───────────────────────────────────────────────────────
    LOGIN = 'login'
    REGISTER = 'register'
    PURPOSE_CHOICES = [
        (LOGIN, 'تسجيل الدخول'),
        (REGISTER, 'إنشاء حساب'),
    ]

    # Hashed phone number — ties this OTP to a specific user without storing their phone.
    phone_hash = models.CharField(max_length=64, db_index=True)

    # SHA-256 of the 6-digit OTP — never the OTP itself.
    otp_hash = models.CharField(max_length=64)

    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)

    # Tracks failed attempts — triggers lockout at OTP_MAX_ATTEMPTS.
    attempts = models.PositiveSmallIntegerField(default=0)

    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)   # Marked True on successful verify or invalidation
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounts_otp_verification'
        verbose_name = 'رمز التحقق'
        verbose_name_plural = 'رموز التحقق'
        indexes = [
            # Optimise the "find valid OTP for this phone+purpose" query
            models.Index(fields=['phone_hash', 'purpose', 'is_used']),
        ]

    def __str__(self):
        return f'OTP [{self.purpose}] — expires {self.expires_at}'
