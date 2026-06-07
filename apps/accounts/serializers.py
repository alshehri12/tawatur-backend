"""
Request/response serializers for the accounts API.
Validation error messages are written in Arabic (MSA) throughout.
"""

import re
from rest_framework import serializers
from .models import User


# ── Shared validator ──────────────────────────────────────────────────────────

def validate_saudi_phone(value: str) -> str:
    """
    Accept Saudi mobile numbers in any of these formats:
      05XXXXXXXX  /  +9665XXXXXXXX  /  9665XXXXXXXX
    Returns the number as-is (normalisation happens in core.hashing).
    """
    cleaned = value.replace(' ', '').replace('-', '')
    pattern = r'^(\+9665|9665|05)\d{8}$'
    if not re.match(pattern, cleaned):
        raise serializers.ValidationError(
            'رقم الجوال غير صالح. أدخل رقم سعودي صحيح (مثال: 05XXXXXXXX).'
        )
    return cleaned


# ── OTP Serializers ───────────────────────────────────────────────────────────

class RequestOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    purpose = serializers.ChoiceField(
        choices=['login', 'register'],
        error_messages={'invalid_choice': 'الغرض غير صالح.'},
    )

    def validate_phone_number(self, value):
        return validate_saudi_phone(value)


class VerifyOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    otp = serializers.CharField(
        min_length=6, max_length=6,
        error_messages={
            'min_length': 'رمز التحقق يجب أن يكون 6 أرقام.',
            'max_length': 'رمز التحقق يجب أن يكون 6 أرقام.',
        },
    )
    purpose = serializers.ChoiceField(choices=['login', 'register'])

    def validate_phone_number(self, value):
        return validate_saudi_phone(value)

    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('رمز التحقق يجب أن يحتوي على أرقام فقط.')
        return value


# ── Registration Serializers ──────────────────────────────────────────────────

class RegisterIndividualSerializer(serializers.Serializer):
    """
    Registers a new individual user.
    Requires a verified OTP (from a prior /request-otp/ call with purpose=register).
    Either national_id OR iqama must be provided.
    """
    phone_number = serializers.CharField(max_length=20)
    otp = serializers.CharField(min_length=6, max_length=6)
    national_id = serializers.CharField(
        max_length=10, required=False, allow_blank=True,
        help_text='رقم الهوية الوطنية (10 أرقام)',
    )
    iqama = serializers.CharField(
        max_length=10, required=False, allow_blank=True,
        help_text='رقم الإقامة (10 أرقام)',
    )

    def validate_phone_number(self, value):
        return validate_saudi_phone(value)

    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('رمز التحقق يجب أن يحتوي على أرقام فقط.')
        return value

    def validate(self, data):
        # At least one identity document must be provided
        if not data.get('national_id') and not data.get('iqama'):
            raise serializers.ValidationError(
                {'identity': 'يجب إدخال رقم الهوية الوطنية أو رقم الإقامة.'}
            )
        return data


class RegisterBusinessSerializer(serializers.Serializer):
    """
    Registers a new business user.
    Requires a verified OTP (purpose=register) + commercial registration number.
    """
    phone_number = serializers.CharField(max_length=20)
    otp = serializers.CharField(min_length=6, max_length=6)
    cr_number = serializers.CharField(
        max_length=20,
        help_text='رقم السجل التجاري',
    )
    business_name = serializers.CharField(
        max_length=255,
        help_text='اسم المنشأة كما هو في السجل التجاري',
    )

    def validate_phone_number(self, value):
        return validate_saudi_phone(value)

    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('رمز التحقق يجب أن يحتوي على أرقام فقط.')
        return value


# ── Verification Serializers (post-registration) ──────────────────────────────

class SubmitIndividualVerificationSerializer(serializers.Serializer):
    """
    Allows an existing individual user to submit (or re-submit) identity data.
    Used if the user skipped verification at registration time.
    """
    national_id = serializers.CharField(max_length=10, required=False, allow_blank=True)
    iqama = serializers.CharField(max_length=10, required=False, allow_blank=True)

    def validate(self, data):
        if not data.get('national_id') and not data.get('iqama'):
            raise serializers.ValidationError(
                {'identity': 'يجب إدخال رقم الهوية الوطنية أو رقم الإقامة.'}
            )
        return data


class SubmitBusinessVerificationSerializer(serializers.Serializer):
    """
    Allows an existing business user to submit (or update) CR data.
    """
    cr_number = serializers.CharField(max_length=20)
    business_name = serializers.CharField(max_length=255)


# ── Profile Serializer ────────────────────────────────────────────────────────

class UserProfileSerializer(serializers.ModelSerializer):
    """
    Read-only profile returned after login / registration, and from GET /auth/me/.
    Never exposes phone number, national ID, or any encrypted/hashed field.
    """
    verification_status = serializers.CharField(read_only=True)
    can_transact = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'user_type',
            # Individual flags
            'identity_submitted',
            'absher_verified',
            # Business fields
            'business_name',
            'cr_submitted',
            'wathiq_verified',
            # Computed
            'verification_status',
            'can_transact',
            'date_joined',
        ]
        read_only_fields = fields
