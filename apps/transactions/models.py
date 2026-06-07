"""
Transactions domain model.

A Transaction represents a request to transfer ownership of a product
from one user (initiator) to another (recipient). The recipient reviews
the request via a shareable link and either approves or rejects it.

Views, services, and URLs for this app are built in Phase 3.
The model is defined here so that the OwnershipRecord FK resolves cleanly.
"""

import uuid
from django.db import models
from django.conf import settings


class Transaction(models.Model):

    # ── Transaction type ──────────────────────────────────────────────────────
    INDIVIDUAL_TO_INDIVIDUAL = 'individual_to_individual'
    BUSINESS_PURCHASE = 'business_purchase'
    BUSINESS_SALE = 'business_sale'

    TRANSACTION_TYPE_CHOICES = [
        (INDIVIDUAL_TO_INDIVIDUAL, 'بين أفراد'),
        (BUSINESS_PURCHASE, 'شراء منشأة'),
        (BUSINESS_SALE, 'بيع منشأة'),
    ]

    # ── Status ────────────────────────────────────────────────────────────────
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    CANCELLED = 'cancelled'
    EXPIRED = 'expired'

    STATUS_CHOICES = [
        (PENDING, 'بانتظار الموافقة'),
        (APPROVED, 'مكتملة'),
        (REJECTED, 'مرفوضة'),
        (CANCELLED, 'ملغاة'),
        (EXPIRED, 'منتهية الصلاحية'),
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
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='received_transactions',
    )

    transaction_type = models.CharField(
        max_length=30, choices=TRANSACTION_TYPE_CHOICES,
        default=INDIVIDUAL_TO_INDIVIDUAL,
    )

    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=PENDING)

    # UUID used as the shareable link token (tawatur://transaction/{link_token})
    link_token = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    expires_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
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


class AuditLog(models.Model):
    """
    Immutable log of every status change on a transaction.
    Written by TransactionService — never updated or deleted.
    """
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
    action = models.CharField(max_length=50)       # e.g. 'created', 'approved', 'rejected'
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
