from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .models import Transaction, AuditLog


class AuditLogInline(TabularInline):
    model = AuditLog
    extra = 0
    readonly_fields = ['actor', 'action', 'old_status', 'new_status', 'timestamp']
    can_delete = False


@admin.register(Transaction)
class TransactionAdmin(ModelAdmin):
    list_display = [
        'id', 'transaction_type', 'status',
        'product', 'initiator',
        'seller_full_name', 'seller_city',
        'device_condition', 'price',
        'created_at',
    ]
    list_filter = ['transaction_type', 'status', 'device_condition']
    search_fields = [
        'id', 'product__brand', 'product__model',
        'seller_full_name', 'seller_city',
    ]
    readonly_fields = [
        'id', 'created_at', 'updated_at', 'approved_at', 'expires_at',
        'get_seller_id_number', 'get_seller_mobile',
    ]
    ordering = ['-created_at']
    inlines = [AuditLogInline]

    fieldsets = (
        ('معلومات المعاملة', {
            'fields': (
                'id', 'transaction_type', 'status',
                'product', 'initiator',
                'created_at', 'approved_at', 'expires_at',
            ),
        }),
        ('بيانات البائع', {
            'fields': (
                'seller_full_name',
                'get_seller_id_number',
                'get_seller_mobile',
                'seller_city',
            ),
        }),
        ('تفاصيل الصفقة', {
            'fields': ('price', 'device_condition', 'seller_terms', 'notes'),
        }),
    )

    @admin.display(description='هوية البائع (مفككة)')
    def get_seller_id_number(self, obj):
        return obj.seller_id_number or '—'

    @admin.display(description='جوال البائع (مفككة)')
    def get_seller_mobile(self, obj):
        return obj.seller_mobile or '—'
