"""
Serializers for the products API.

Three tiers of product detail:
  1. ProductPublicSerializer   — safe for any authenticated user (no IMEI/serial).
  2. ProductOwnerSerializer    — extends public with decrypted identifiers for the owner.
  3. OwnershipHistorySummarySerializer — chain stats with no personal data.
"""

from rest_framework import serializers
from .models import Product, OwnershipRecord


# ── Input Serializer ──────────────────────────────────────────────────────────

class CreateProductSerializer(serializers.Serializer):
    """Validates the request body for POST /api/v1/products/."""

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

    # Optional — at least one identifier is strongly recommended but not enforced
    imei_1         = serializers.CharField(max_length=15,   required=False, allow_blank=True)
    imei_2         = serializers.CharField(max_length=15,   required=False, allow_blank=True)
    serial_number  = serializers.CharField(max_length=50,   required=False, allow_blank=True)
    notes          = serializers.CharField(max_length=500,  required=False, allow_blank=True)
    purchase_terms = serializers.CharField(max_length=2000, required=False, allow_blank=True)

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


# ── Output Serializers ────────────────────────────────────────────────────────

class ProductPublicSerializer(serializers.ModelSerializer):
    """
    Safe to return to any authenticated user.
    Never exposes IMEI, serial, or owner identity.
    """
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    condition_display = serializers.CharField(source='get_condition_display', read_only=True)
    trust_level_display = serializers.CharField(source='get_trust_level_display', read_only=True)
    current_owner_since = serializers.SerializerMethodField()
    total_owners = serializers.SerializerMethodField()
    chain_integrity = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'category', 'category_display',
            'brand', 'model',
            'condition', 'condition_display',
            'trust_score', 'trust_level', 'trust_level_display',
            'chain_integrity',
            'total_owners',
            'current_owner_since',
            'registered_at',
        ]

    def get_current_owner_since(self, obj):
        record = obj.ownership_records.filter(is_current=True).only('start_date').first()
        return record.start_date if record else None

    def get_total_owners(self, obj):
        return obj.ownership_records.count()


class ProductOwnerSerializer(ProductPublicSerializer):
    """
    Extended view for the product's current owner — includes decrypted identifiers.
    Only returned when request.user is the current owner.
    """
    imei_1 = serializers.SerializerMethodField()
    imei_2 = serializers.SerializerMethodField()
    serial_number = serializers.SerializerMethodField()

    class Meta(ProductPublicSerializer.Meta):
        fields = ProductPublicSerializer.Meta.fields + [
            'imei_1', 'imei_2', 'serial_number', 'notes', 'purchase_terms',
        ]

    def get_imei_1(self, obj):
        return obj.imei_1 or None      # property on model, uses decrypt()

    def get_imei_2(self, obj):
        return obj.imei_2 or None

    def get_serial_number(self, obj):
        return obj.serial_number or None


# ── Ownership History ─────────────────────────────────────────────────────────

class OwnershipRecordPublicSerializer(serializers.ModelSerializer):
    """
    One record in the public ownership history timeline.
    Shows dates and transfer type — never the owner's identity.
    """
    transfer_type_display = serializers.CharField(source='get_transfer_type_display', read_only=True)
    owner_verified = serializers.SerializerMethodField()

    class Meta:
        model = OwnershipRecord
        fields = [
            'id',
            'transfer_type', 'transfer_type_display',
            'start_date', 'end_date',
            'is_current',
            'owner_verified',   # True/False — does NOT reveal who the owner is
        ]

    def get_owner_verified(self, obj):
        return obj.owner.can_transact


class OwnershipHistorySummarySerializer(serializers.Serializer):
    """
    High-level summary for GET /api/v1/products/{id}/ownership-history/.
    No personal data, only chain statistics.
    """
    total_owners = serializers.IntegerField()
    first_recorded_date = serializers.DateTimeField()
    latest_transfer_date = serializers.DateTimeField()
    chain_integrity = serializers.IntegerField()
    verified_transfer_count = serializers.IntegerField()
    trust_score = serializers.IntegerField()
    trust_level = serializers.CharField()
    trust_level_display = serializers.CharField()
    timeline = OwnershipRecordPublicSerializer(many=True)


class TrustScoreSerializer(serializers.Serializer):
    """Response for GET /api/v1/products/{id}/trust-score/."""
    trust_score = serializers.IntegerField()
    trust_level = serializers.CharField()
    trust_level_display = serializers.CharField()
    chain_integrity = serializers.IntegerField()
    breakdown = serializers.DictField()
