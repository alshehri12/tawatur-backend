"""
Transactions domain model.

A Transaction records a direct purchase: the buyer (initiator) registers
the product they bought, then documents the seller's info to complete the
ownership transfer. No link-sharing or approval step — completed immediately.
"""

import uuid
from django.db import models
from django.conf import settings


class Transaction(models.Model):

    # ── Transaction type ──────────────────────────────────────────────────────
    DIRECT_PURCHASE          = 'direct_purchase'
    # Legacy types — kept so existing DB rows are still valid
    INDIVIDUAL_TO_INDIVIDUAL = 'individual_to_individual'
    BUSINESS_PURCHASE        = 'business_purchase'
    BUSINESS_SALE            = 'business_sale'

    TRANSACTION_TYPE_CHOICES = [
        (DIRECT_PURCHASE,          'شراء مباشر'),
        (INDIVIDUAL_TO_INDIVIDUAL, 'بين أفراد'),
        (BUSINESS_PURCHASE,        'شراء منشأة'),
        (BUSINESS_SALE,            'بيع منشأة'),
    ]

    # ── Status ────────────────────────────────────────────────────────────────
    PENDING   = 'pending'
    APPROVED  = 'approved'
    REJECTED  = 'rejected'
    CANCELLED = 'cancelled'
    EXPIRED   = 'expired'

    STATUS_CHOICES = [
        (PENDING,   'بانتظار الموافقة'),
        (APPROVED,  'مكتملة'),
        (REJECTED,  'مرفوضة'),
        (CANCELLED, 'ملغاة'),
        (EXPIRED,   'منتهية الصلاحية'),
    ]

    # ── Device condition ──────────────────────────────────────────────────────
    CONDITION_NEW  = 'new'
    CONDITION_USED = 'used'
    DEVICE_CONDITION_CHOICES = [
        (CONDITION_NEW,  'جديد'),
        (CONDITION_USED, 'مستعمل'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    initiator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='initiated_transactions',
    )
    # Null for DIRECT_PURCHASE — the seller is not a platform user.
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='received_transactions',
        null=True, blank=True,
    )

    transaction_type = models.CharField(
        max_length=30, choices=TRANSACTION_TYPE_CHOICES,
        default=DIRECT_PURCHASE,
    )

    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    device_condition = models.CharField(
        max_length=10, choices=DEVICE_CONDITION_CHOICES, blank=True, default='',
    )
    seller_terms = models.TextField(blank=True, default='')
    notes = models.TextField(blank=True, default='')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=PENDING)

    # ── Direct-purchase seller info ───────────────────────────────────────────
    # The seller is not a registered user; their details are entered by the buyer.
    seller_full_name         = models.CharField(max_length=200, blank=True, default='')
    seller_id_number_encrypted = models.TextField(blank=True, default='')   # Saudi ID / Iqama
    # HMAC hash of the seller's ID/Iqama — lets us recognize the seller later
    # if they register their own Tawatur account with the same national ID or
    # Iqama, so they can see the contracts where they were the seller.
    seller_id_number_hash    = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    seller_mobile_encrypted  = models.TextField(blank=True, default='')
    # HMAC hash of the seller's mobile (same normalization as User.phone_hash)
    # — the moment the seller registers a Tawatur account with this phone
    # number, this transaction shows up as a pending request addressed to them.
    seller_mobile_hash       = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    seller_city              = models.CharField(max_length=100, blank=True, default='')

    link_token = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    expires_at = models.DateTimeField()

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'transactions_transaction'
        verbose_name = 'معاملة'
        verbose_name_plural = 'المعاملات'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['link_token']),
        ]

    def __str__(self):
        return f'معاملة {self.get_transaction_type_display()} — {self.status}'

    # ── Decrypted seller info (only used server-side, e.g. in PDF) ────────────
    @property
    def seller_id_number(self) -> str:
        if not self.seller_id_number_encrypted:
            return ''
        from core.encryption import decrypt
        return decrypt(self.seller_id_number_encrypted)

    @property
    def seller_mobile(self) -> str:
        if not self.seller_mobile_encrypted:
            return ''
        from core.encryption import decrypt
        return decrypt(self.seller_mobile_encrypted)


class AuditLog(models.Model):
    """Immutable log of every status change on a transaction."""
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='audit_logs',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='audit_logs',
    )
    action = models.CharField(max_length=50)
    old_status = models.CharField(max_length=15, blank=True)
    new_status = models.CharField(max_length=15, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    device_fingerprint_hash = models.CharField(max_length=64, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'transactions_audit_log'
        verbose_name = 'سجل مراجعة'
        verbose_name_plural = 'سجلات المراجعة'
        ordering = ['timestamp']

    def __str__(self):
        return f'{self.action} — {self.timestamp}'
