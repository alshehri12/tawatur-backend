from django.contrib import admin
from .models import Certificate


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = [
        'certificate_number', 'certificate_type', 'product',
        'owner', 'is_valid', 'issued_at',
    ]
    list_filter = ['certificate_type', 'is_valid']
    search_fields = ['certificate_number', 'product__id']
    readonly_fields = [
        'id', 'certificate_number', 'issued_at',
        'qr_code_path', 'pdf_path', 'verification_url',
    ]
    ordering = ['-issued_at']

    actions = ['revoke_certificates']

    @admin.action(description='إلغاء الشهادات المحددة')
    def revoke_certificates(self, request, queryset):
        queryset.update(is_valid=False)
