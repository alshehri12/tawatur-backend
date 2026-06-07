from django.contrib import admin
from .models import Product, OwnershipRecord


class OwnershipRecordInline(admin.TabularInline):
    model = OwnershipRecord
    extra = 0
    readonly_fields = ['id', 'owner', 'start_date', 'end_date', 'transfer_type', 'is_current']
    can_delete = False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'category', 'brand', 'model', 'condition',
        'trust_score', 'trust_level', 'registered_by', 'registered_at', 'is_active',
    ]
    list_filter = ['category', 'condition', 'trust_level', 'is_active']
    search_fields = ['id', 'brand', 'model', 'imei_1_hash', 'imei_2_hash', 'serial_hash']
    readonly_fields = [
        'id', 'imei_1_hash', 'imei_2_hash', 'serial_hash',
        'imei_1_encrypted', 'imei_2_encrypted', 'serial_encrypted',
        'registered_by', 'registered_at', 'trust_score', 'trust_level',
    ]
    ordering = ['-registered_at']
    inlines = [OwnershipRecordInline]

    fieldsets = (
        ('تفاصيل المنتج', {
            'fields': ('id', 'category', 'brand', 'model', 'condition', 'notes'),
        }),
        ('المعرّفات (مشفرة)', {
            'fields': (
                'imei_1_encrypted', 'imei_1_hash',
                'imei_2_encrypted', 'imei_2_hash',
                'serial_encrypted', 'serial_hash',
            ),
            'classes': ('collapse',),
        }),
        ('الملكية والثقة', {
            'fields': ('registered_by', 'registered_at', 'trust_score', 'trust_level', 'is_active'),
        }),
    )


@admin.register(OwnershipRecord)
class OwnershipRecordAdmin(admin.ModelAdmin):
    list_display = ['id', 'product', 'owner', 'transfer_type', 'is_current', 'start_date', 'end_date']
    list_filter = ['transfer_type', 'is_current']
    search_fields = ['product__id', 'owner__phone_hash']
    readonly_fields = ['id', 'start_date']
    ordering = ['-start_date']
