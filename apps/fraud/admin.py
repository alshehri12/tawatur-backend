from django.contrib import admin
from .models import FraudAlert


@admin.register(FraudAlert)
class FraudAlertAdmin(admin.ModelAdmin):
    list_display = ['id', 'alert_type', 'severity', 'status', 'product', 'user', 'created_at']
    list_filter = ['alert_type', 'severity', 'status']
    search_fields = ['description', 'product__id']
    readonly_fields = ['created_at', 'resolved_at']
    ordering = ['-created_at']

    # Quick-action: mark selected alerts as resolved
    actions = ['mark_resolved', 'mark_dismissed']

    @admin.action(description='تحديد كمحلولة')
    def mark_resolved(self, request, queryset):
        from django.utils import timezone
        queryset.update(status=FraudAlert.RESOLVED, resolved_at=timezone.now(), resolved_by=request.user)

    @admin.action(description='تحديد كمرفوضة')
    def mark_dismissed(self, request, queryset):
        queryset.update(status=FraudAlert.DISMISSED)
