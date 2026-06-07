"""
Products domain models:
  - Product       : a registered device with encrypted identifiers.
  - OwnershipRecord : one node in the device's ownership chain.
"""

import uuid
from django.db import models
from django.conf import settings


class Product(models.Model):
    """
    A physical device registered on تواتر.

    Sensitive identifiers (IMEI, serial number) are stored in two forms:
      - Encrypted text  : readable back by the current owner.
      - HMAC hash       : used for duplicate-detection lookups and DB indexes.

    The trust_score and trust_level are recalculated by TrustScoreService
    every time the ownership chain changes.
    """

    # ── Category choices ──────────────────────────────────────────────────────
    SMARTPHONE = 'smartphone'
    TABLET = 'tablet'
    LAPTOP = 'laptop'
    SMARTWATCH = 'smartwatch'
    GAMING_CONSOLE = 'gaming_console'
    CAMERA = 'camera'

    CATEGORY_CHOICES = [
        (SMARTPHONE, 'هاتف ذكي'),
        (TABLET, 'جهاز لوحي'),
        (LAPTOP, 'حاسوب محمول'),
        (SMARTWATCH, 'ساعة ذكية'),
        (GAMING_CONSOLE, 'جهاز ألعاب'),
        (CAMERA, 'كاميرا'),
    ]

    # ── Condition choices ─────────────────────────────────────────────────────
    CONDITION_NEW = 'new'
    CONDITION_EXCELLENT = 'excellent'
    CONDITION_GOOD = 'good'
    CONDITION_FAIR = 'fair'
    CONDITION_POOR = 'poor'

    CONDITION_CHOICES = [
        (CONDITION_NEW, 'جديد'),
        (CONDITION_EXCELLENT, 'ممتاز'),
        (CONDITION_GOOD, 'جيد'),
        (CONDITION_FAIR, 'مقبول'),
        (CONDITION_POOR, 'ضعيف'),
    ]

    # ── Trust level choices ───────────────────────────────────────────────────
    TRUST_EXCELLENT = 'excellent'
    TRUST_HIGH = 'high'
    TRUST_MEDIUM = 'medium'
    TRUST_LOW = 'low'

    TRUST_LEVEL_CHOICES = [
        (TRUST_EXCELLENT, 'ممتاز'),
        (TRUST_HIGH, 'عالٍ'),
        (TRUST_MEDIUM, 'متوسط'),
        (TRUST_LOW, 'منخفض'),
    ]

    # ── Fields ────────────────────────────────────────────────────────────────
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=100)        # e.g. "iPhone 16 Pro"
    condition = models.CharField(max_length=15, choices=CONDITION_CHOICES)
    notes = models.TextField(blank=True, default='')

    # ── IMEI 1 (primary SIM slot) ─────────────────────────────────────────────
    imei_1_encrypted = models.TextField(blank=True, default='')
    # Unique=False because two products can share an IMEI only if detected as fraud
    imei_1_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    # ── IMEI 2 (dual-SIM second slot) ────────────────────────────────────────
    imei_2_encrypted = models.TextField(blank=True, default='')
    imei_2_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    # ── Serial number ─────────────────────────────────────────────────────────
    serial_encrypted = models.TextField(blank=True, default='')
    serial_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    # ── Ownership metadata ────────────────────────────────────────────────────
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='registered_products',
    )
    registered_at = models.DateTimeField(auto_now_add=True)

    # ── Trust score (recalculated on every ownership change) ──────────────────
    trust_score = models.PositiveSmallIntegerField(default=50)
    trust_level = models.CharField(
        max_length=10, choices=TRUST_LEVEL_CHOICES, default=TRUST_MEDIUM
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'products_product'
        verbose_name = 'منتج'
        verbose_name_plural = 'المنتجات'
        ordering = ['-registered_at']

    def __str__(self):
        return f'{self.get_category_display()} — {self.brand} {self.model}'

    # ── Decrypted property helpers (used by owner-only serializer) ────────────

    @property
    def imei_1(self) -> str:
        from core.encryption import decrypt
        return decrypt(self.imei_1_encrypted) if self.imei_1_encrypted else ''

    @property
    def imei_2(self) -> str:
        from core.encryption import decrypt
        return decrypt(self.imei_2_encrypted) if self.imei_2_encrypted else ''

    @property
    def serial_number(self) -> str:
        from core.encryption import decrypt
        return decrypt(self.serial_encrypted) if self.serial_encrypted else ''

    @property
    def current_owner(self):
        """Return the OwnershipRecord that is currently active."""
        return self.ownership_records.filter(is_current=True).select_related('owner').first()

    @property
    def chain_integrity(self) -> int:
        """
        Percentage of ownership records belonging to verified users.
        100% = every owner in the chain has submitted identity verification.
        """
        records = self.ownership_records.all()
        total = records.count()
        if total == 0:
            return 0
        verified = records.filter(owner__identity_submitted=True).count()
        return int((verified / total) * 100)


class OwnershipRecord(models.Model):
    """
    One link in a product's ownership chain.

    Rules:
      - Exactly ONE record per product has is_current=True at any time.
      - When a transaction is approved, the old record's end_date is set,
        is_current is set to False, and a new record is created.
      - The first record (transfer_type='initial') is created when the
        product is registered — it has no linked transaction.
    """

    INITIAL = 'initial'
    PURCHASE = 'purchase'
    GIFT = 'gift'
    TRADE = 'trade'
    OTHER = 'other'

    TRANSFER_TYPE_CHOICES = [
        (INITIAL, 'تسجيل أولي'),
        (PURCHASE, 'شراء'),
        (GIFT, 'هدية'),
        (TRADE, 'مبادلة'),
        (OTHER, 'أخرى'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='ownership_records',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='ownership_records',
    )

    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(null=True, blank=True)   # Null while is_current=True
    is_current = models.BooleanField(default=True, db_index=True)

    transfer_type = models.CharField(
        max_length=10, choices=TRANSFER_TYPE_CHOICES, default=INITIAL
    )

    # Linked transaction — null only for the first (initial) ownership record
    transaction = models.ForeignKey(
        'transactions.Transaction',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='ownership_records',
    )

    class Meta:
        db_table = 'products_ownership_record'
        verbose_name = 'سجل ملكية'
        verbose_name_plural = 'سجلات الملكية'
        ordering = ['start_date']
        indexes = [
            models.Index(fields=['product', 'is_current']),
        ]

    def __str__(self):
        status = 'حالي' if self.is_current else 'سابق'
        return f'{self.product} — {status} ({self.get_transfer_type_display()})'
