"""
Fraud detection models.

FraudAlert is created automatically by the system when suspicious patterns
are detected (duplicate IMEI, duplicate serial, excessive transfers, etc.).
Admins review and resolve alerts from the dashboard.
"""

from django.db import models
from django.conf import settings


class FraudAlert(models.Model):

    # ── Alert type choices ────────────────────────────────────────────────────
    DUPLICATE_IMEI = 'duplicate_imei'
    DUPLICATE_SERIAL = 'duplicate_serial'
    EXCESSIVE_TRANSFERS = 'excessive_transfers'
    EXCESSIVE_REGISTRATIONS = 'excessive_registrations'
    SUSPICIOUS_ACTIVITY = 'suspicious_activity'

    ALERT_TYPE_CHOICES = [
        (DUPLICATE_IMEI, 'IMEI مكرر'),
        (DUPLICATE_SERIAL, 'رقم تسلسلي مكرر'),
        (EXCESSIVE_TRANSFERS, 'تحويلات مفرطة'),
        (EXCESSIVE_REGISTRATIONS, 'تسجيلات مفرطة'),
        (SUSPICIOUS_ACTIVITY, 'نشاط مشبوه'),
    ]

    # ── Severity ──────────────────────────────────────────────────────────────
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    CRITICAL = 'critical'

    SEVERITY_CHOICES = [
        (LOW, 'منخفض'),
        (MEDIUM, 'متوسط'),
        (HIGH, 'عالٍ'),
        (CRITICAL, 'حرج'),
    ]

    # ── Status ────────────────────────────────────────────────────────────────
    OPEN = 'open'
    INVESTIGATING = 'investigating'
    RESOLVED = 'resolved'
    DISMISSED = 'dismissed'

    STATUS_CHOICES = [
        (OPEN, 'مفتوح'),
        (INVESTIGATING, 'قيد التحقيق'),
        (RESOLVED, 'محلول'),
        (DISMISSED, 'مرفوض'),
    ]

    alert_type = models.CharField(max_length=30, choices=ALERT_TYPE_CHOICES)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default=MEDIUM)

    # The product/user/transaction that triggered the alert (all optional)
    product = models.ForeignKey(
        'products.Product',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='fraud_alerts',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='fraud_alerts',
    )

    description = models.TextField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=OPEN)

    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='resolved_fraud_alerts',
    )

    class Meta:
        db_table = 'fraud_alert'
        verbose_name = 'تنبيه احتيال'
        verbose_name_plural = 'تنبيهات الاحتيال'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'severity']),
            models.Index(fields=['product', 'status']),
        ]

    def __str__(self):
        return f'[{self.severity.upper()}] {self.get_alert_type_display()} — {self.status}'
