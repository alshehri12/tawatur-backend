"""
Certificate model.

A Certificate is a permanent, tamper-evident record that proves ownership
or documents an ownership transfer. Each certificate has:
  - A human-readable number  (TW-2026-ABCD1234)
  - A QR code image          (links to the public verification URL)
  - A PDF file               (downloadable by the certificate owner)
  - A public verification URL (accessible by anyone, no login required)

Three types are supported:
  1. ownership_transfer  — auto-generated when a transaction is approved.
  2. current_ownership   — generated on demand by the current owner.
  3. history_report      — product chain summary, no personal data.
"""

import uuid
from django.db import models
from django.conf import settings


class Certificate(models.Model):

    OWNERSHIP_TRANSFER = 'ownership_transfer'
    CURRENT_OWNERSHIP = 'current_ownership'
    HISTORY_REPORT = 'history_report'

    TYPE_CHOICES = [
        (OWNERSHIP_TRANSFER, 'شهادة نقل ملكية'),
        (CURRENT_OWNERSHIP, 'شهادة ملكية حالية'),
        (HISTORY_REPORT, 'تقرير تاريخ المنتج'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Human-readable identifier printed on the certificate and encoded in the QR
    certificate_number = models.CharField(max_length=20, unique=True, db_index=True)

    # The transaction that triggered this certificate (null for on-demand types)
    transaction = models.OneToOneField(
        'transactions.Transaction',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='certificate',
    )

    product = models.ForeignKey(
        'products.Product',
        on_delete=models.PROTECT,
        related_name='certificates',
    )

    # The user who owns this certificate (recipient of transfer, or requester)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='certificates',
    )

    certificate_type = models.CharField(max_length=20, choices=TYPE_CHOICES)

    # Paths relative to MEDIA_ROOT (or S3 keys in production)
    qr_code_path = models.CharField(max_length=255, blank=True, default='')
    pdf_path = models.CharField(max_length=255, blank=True, default='')

    # The public URL embedded in the QR and on the certificate itself
    verification_url = models.CharField(max_length=255, blank=True, default='')

    issued_at = models.DateTimeField(auto_now_add=True)

    # Can be set to False if a dispute voids the certificate
    is_valid = models.BooleanField(default=True)

    class Meta:
        db_table = 'certificates_certificate'
        verbose_name = 'شهادة'
        verbose_name_plural = 'الشهادات'
        ordering = ['-issued_at']

    def __str__(self):
        return f'{self.certificate_number} — {self.get_certificate_type_display()}'

    @property
    def pdf_url(self) -> str:
        """Full URL to download the PDF (works for both local and S3 storage)."""
        if not self.pdf_path:
            return ''
        from django.conf import settings as s
        return f'{s.MEDIA_URL}{self.pdf_path}'

    @property
    def qr_code_url(self) -> str:
        """Full URL to the QR code image."""
        if not self.qr_code_path:
            return ''
        from django.conf import settings as s
        return f'{s.MEDIA_URL}{self.qr_code_path}'
