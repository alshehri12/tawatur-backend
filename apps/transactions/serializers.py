"""
Serializers for the transactions API.
"""

from decimal import Decimal
from rest_framework import serializers
from apps.products.models import Product
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


class CreateRegisteredPurchaseSerializer(serializers.Serializer):
    """
    Validates the body for POST /api/v1/transactions/register-purchase/.

    Single-step flow: the buyer registers the device they just bought AND
    documents the purchase in one call — replaces the separate "register a
    product" step that used to end at "منتجاتي" with nothing else happening.

    Seller fields are unchanged from CreateDirectPurchaseSerializer — the
    seller still doesn't need a platform account. The difference is the
    transaction is created PENDING, not auto-approved: the buyer shares the
    confirmation link with the seller, who reviews and accepts/rejects it
    (see CreateRegisteredPurchaseView / SellerConfirmView).
    """

    # ── Product fields (device being registered) ──────────────────────────────
    category = serializers.ChoiceField(
        choices=Product.CATEGORY_CHOICES,
        error_messages={'invalid_choice': 'الفئة غير صالحة.'},
    )
    brand = serializers.CharField(max_length=100)
    model = serializers.CharField(max_length=100)
    condition = serializers.ChoiceField(
        choices=Product.CONDITION_CHOICES,
        error_messages={'invalid_choice': 'الحالة غير صالحة.'},
    )
    imei_1        = serializers.CharField(max_length=15,  required=False, allow_blank=True)
    imei_2        = serializers.CharField(max_length=15,  required=False, allow_blank=True)
    serial_number = serializers.CharField(max_length=50,  required=False, allow_blank=True)
    product_notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')

    # ── Seller information (the seller does not need a platform account) ──────
    seller_full_name = serializers.CharField(max_length=200)
    seller_id_number = serializers.CharField(max_length=20)   # Saudi ID (10 digits) or Iqama
    seller_mobile    = serializers.CharField(max_length=20)
    seller_city      = serializers.CharField(max_length=100)

    # ── Deal details ───────────────────────────────────────────────────────────
    price = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, allow_null=True,
        min_value=Decimal('0'),
    )
    seller_terms = serializers.CharField(max_length=2000, required=False, allow_blank=True, default='')
    notes        = serializers.CharField(max_length=500,  required=False, allow_blank=True, default='')

    def validate_imei_1(self, value):
        if value and (not value.isdigit() or len(value) not in (14, 15)):
            raise serializers.ValidationError('IMEI يجب أن يكون 14 أو 15 رقمًا.')
        return value

    def validate_imei_2(self, value):
        if value and (not value.isdigit() or len(value) not in (14, 15)):
            raise serializers.ValidationError('IMEI يجب أن يكون 14 أو 15 رقمًا.')
        return value

    def validate(self, data):
        if not any([data.get('imei_1'), data.get('imei_2'), data.get('serial_number')]):
            raise serializers.ValidationError(
                'يجب إدخال رقم IMEI أو الرقم التسلسلي واحد على الأقل.'
            )
        return data


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

    # Public link the buyer shares with the seller to confirm/reject the deal
    confirm_url = serializers.SerializerMethodField()

    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + [
            'notes', 'seller_terms',
            'seller_full_name', 'seller_id_number', 'seller_mobile', 'seller_city',
            'certificate_id', 'certificate_pdf_url',
            'confirm_url',
            'audit_logs',
        ]

    def get_confirm_url(self, obj):
        if obj.status != Transaction.PENDING:
            return None
        request = self.context.get('request')
        path = f'/confirm/{obj.link_token}/'
        return request.build_absolute_uri(path) if request else path

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
