"""
Serializers for the transactions API.
"""

from decimal import Decimal
from rest_framework import serializers
from .models import Transaction, AuditLog
from apps.accounts.serializers import validate_saudi_phone


# ── Input Serializers ─────────────────────────────────────────────────────────

class CreateTransactionSerializer(serializers.Serializer):
    """Validates the body for POST /api/v1/transactions/."""

    product_id = serializers.UUIDField()
    recipient_phone = serializers.CharField(max_length=20)
    transaction_type = serializers.ChoiceField(
        choices=Transaction.TRANSACTION_TYPE_CHOICES,
        error_messages={'invalid_choice': 'نوع المعاملة غير صالح.'},
    )
    price = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, allow_null=True,
        min_value=Decimal('0'),
    )
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate_recipient_phone(self, value):
        return validate_saudi_phone(value)


# ── Output Serializers ────────────────────────────────────────────────────────

class TransactionPartySerializer(serializers.Serializer):
    """
    Minimal info about a transaction party (initiator or recipient).
    Never exposes the phone number — only verification status and user type.
    """
    user_type = serializers.CharField()
    verification_status = serializers.CharField()
    business_name = serializers.CharField(allow_null=True)


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ['action', 'old_status', 'new_status', 'timestamp']


class TransactionSerializer(serializers.ModelSerializer):
    """
    List view — used in GET /api/v1/transactions/my/.
    Minimal fields for listing.
    """
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    product_summary = serializers.SerializerMethodField()
    is_initiator = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_type', 'transaction_type_display',
            'status', 'status_display',
            'price', 'created_at', 'expires_at', 'approved_at',
            'product_summary', 'is_initiator',
        ]

    def get_product_summary(self, obj):
        return {
            'id': str(obj.product.id),
            'brand': obj.product.brand,
            'model': obj.product.model,
            'category_display': obj.product.get_category_display(),
        }

    def get_is_initiator(self, obj):
        request = self.context.get('request')
        return request and request.user == obj.initiator


class TransactionDetailSerializer(TransactionSerializer):
    """
    Full detail view — returned to both parties of a specific transaction.
    Includes audit log and link token for sharing.
    """
    initiator_info = serializers.SerializerMethodField()
    recipient_info = serializers.SerializerMethodField()
    audit_logs = AuditLogSerializer(many=True, read_only=True)
    share_link = serializers.SerializerMethodField()

    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + [
            'notes',
            'link_token',
            'share_link',
            'initiator_info',
            'recipient_info',
            'audit_logs',
        ]

    def get_initiator_info(self, obj):
        return TransactionPartySerializer({
            'user_type': obj.initiator.user_type,
            'verification_status': obj.initiator.verification_status,
            'business_name': obj.initiator.business_name,
        }).data

    def get_recipient_info(self, obj):
        return TransactionPartySerializer({
            'user_type': obj.recipient.user_type,
            'verification_status': obj.recipient.verification_status,
            'business_name': obj.recipient.business_name,
        }).data

    def get_share_link(self, obj):
        # Deep link for the iOS/Android app
        # tawatur://transaction/<token>
        return f'tawatur://transaction/{obj.link_token}'
