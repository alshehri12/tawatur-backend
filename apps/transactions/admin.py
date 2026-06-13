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
    list_display = ['id', 'transaction_type', 'status', 'product', 'initiator', 'created_at', 'expires_at']
    list_filter = ['transaction_type', 'status']
    search_fields = ['id', 'product__id', 'link_token']
    readonly_fields = ['id', 'link_token', 'created_at', 'updated_at', 'approved_at']
    ordering = ['-created_at']
    inlines = [AuditLogInline]
