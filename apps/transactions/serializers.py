"""
Serializers for the transactions API.
"""

from decimal import Decimal
from rest_framework import serializers
from .models import Transaction, AuditLog


# ── Input Serializer ──────────────────────────────────────────────────────────

class CreateDirectPurchaseSerializer(serializers.Serializer):
    """Validates the body for POST /api/v1/transactions/ (buyer-initiated direct purchase)."""

    product_id = serializers.UUIDField()

    # Seller information (the seller does not need a platform account)
    seller_full_name = serializers.CharField(max_length=200)
    seller_id_number = serializers.CharField(max_length=20)   # Saudi ID (10 digits) or Iqama
    seller_mobile    = serializers.CharField(max_length=20)
    seller_city      = serializers.CharField(max_length=100)

    # Deal details
    price = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, allow_null=True,
        min_value=Decimal('0'),
    )
    device_condition = serializers.ChoiceField(
        choices=Transaction.DEVICE_CONDITION_CHOICES,
        required=False, allow_blank=True, default='',
    )
    seller_terms = serializers.CharField(max_length=2000, required=False, allow_blank=True, default='')
    notes        = serializers.CharField(max_length=500,  required=False, allow_blank=True, default='')


# ── Output Serializers ────────────────────────────────────────────────────────

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ['action', 'old_status', 'new_status', 'timestamp']


class TransactionSerializer(serializers.ModelSerializer):
    """List view — used in GET /api/v1/transactions/my/."""
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    status_display           = serializers.CharField(source='get_status_display', read_only=True)
    product_summary          = serializers.SerializerMethodField()
    is_initiator             = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_type', 'transaction_type_display',
            'status', 'status_display',
            'price', 'device_condition',
            'created_at', 'expires_at', 'approved_at',
            'product_summary', 'is_initiator',
        ]

    def get_product_summary(self, obj):
        return {
            'id':               str(obj.product.id),
            'brand':            obj.product.brand,
            'model':            obj.product.model,
            'category_display': obj.product.get_category_display(),
        }

    def get_is_initiator(self, obj):
        request = self.context.get('request')
        return request and request.user == obj.initiator


class TransactionDetailSerializer(TransactionSerializer):
    """Full detail view returned to the buyer after completing a direct purchase."""
    audit_logs = AuditLogSerializer(many=True, read_only=True)

    # Seller info — decrypted and returned to the buyer only
    seller_id_number  = serializers.SerializerMethodField()
    seller_mobile     = serializers.SerializerMethodField()

    # Certificate — included if already generated
    certificate_id      = serializers.SerializerMethodField()
    certificate_pdf_url = serializers.SerializerMethodField()

    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + [
            'notes', 'seller_terms',
            'seller_full_name', 'seller_id_number', 'seller_mobile', 'seller_city',
            'certificate_id', 'certificate_pdf_url',
            'audit_logs',
        ]

    def get_seller_id_number(self, obj):
        return obj.seller_id_number

    def get_seller_mobile(self, obj):
        return obj.seller_mobile

    def get_certificate_id(self, obj):
        try:
            return str(obj.certificate.id)
        except Exception:
            return None

    def get_certificate_pdf_url(self, obj):
        try:
            cert = obj.certificate
            if not cert or not cert.pdf_path:
                return None
            request = self.context.get('request')
            url = f'/media/{cert.pdf_path}'
            return request.build_absolute_uri(url) if request else url
        except Exception:
            return None
