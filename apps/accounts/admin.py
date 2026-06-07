"""
Django Admin registration for the accounts app.
Admins can search users, view verification status, and manually
flip absher_verified / wathiq_verified (simulating real gov. confirmation).
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, OTPVerification


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    # Columns shown in the list view
    list_display = [
        'id', 'user_type', 'business_name',
        'identity_submitted', 'absher_verified',
        'cr_submitted', 'wathiq_verified',
        'is_active', 'is_staff', 'date_joined',
    ]
    list_filter = [
        'user_type', 'identity_submitted', 'absher_verified',
        'cr_submitted', 'wathiq_verified', 'is_active',
    ]
    search_fields = ['id', 'phone_hash', 'business_name']
    ordering = ['-date_joined']
    readonly_fields = ['id', 'phone_hash', 'phone_number_encrypted', 'date_joined', 'device_fingerprint_hash']

    # Override default UserAdmin fieldsets (which expect 'username' / 'email')
    fieldsets = (
        ('الهوية', {
            'fields': ('id', 'phone_hash', 'phone_number_encrypted', 'user_type'),
        }),
        ('التحقق — فرد', {
            'fields': ('national_id_hash', 'iqama_hash', 'identity_submitted', 'absher_verified', 'absher_verified_at'),
            'classes': ('collapse',),
        }),
        ('التحقق — جهة تجارية', {
            'fields': ('cr_number_hash', 'business_name', 'cr_submitted', 'wathiq_verified'),
            'classes': ('collapse',),
        }),
        ('الأمان', {
            'fields': ('device_fingerprint_hash',),
            'classes': ('collapse',),
        }),
        ('الصلاحيات', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('التواريخ', {
            'fields': ('date_joined', 'last_login'),
        }),
    )

    # Fieldsets used when creating a new user from the admin
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('user_type', 'password1', 'password2'),
        }),
    )


@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'purpose', 'attempts', 'is_used', 'expires_at', 'created_at']
    list_filter = ['purpose', 'is_used']
    search_fields = ['phone_hash']
    readonly_fields = ['phone_hash', 'otp_hash', 'created_at']
    ordering = ['-created_at']
