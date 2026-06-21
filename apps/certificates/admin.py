from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from .models import Certificate


@admin.register(Certificate)
class CertificateAdmin(ModelAdmin):
    list_display = [
        'certificate_number', 'certificate_type', 'product',
        'owner', 'is_valid', 'pdf_download_link', 'issued_at',
    ]
    list_filter = ['certificate_type', 'is_valid']
    search_fields = ['certificate_number', 'product__brand', 'product__model']
    readonly_fields = [
        'id', 'certificate_number', 'issued_at',
        'qr_code_path', 'pdf_path', 'verification_url',
        'pdf_download_link',
    ]
    ordering = ['-issued_at']

    fieldsets = (
        ('الشهادة', {
            'fields': (
                'id', 'certificate_number', 'certificate_type',
                'product', 'owner', 'transaction',
                'is_valid', 'issued_at',
            ),
        }),
        ('الملفات والتحقق', {
            'fields': ('pdf_download_link', 'verification_url', 'qr_code_path', 'pdf_path'),
        }),
    )

    actions = ['revoke_certificates']

    @admin.display(description='تحميل PDF')
    def pdf_download_link(self, obj):
        if not obj.pdf_path:
            return '—'
        from django.conf import settings
        url = f'{settings.MEDIA_URL}{obj.pdf_path}'
        return format_html(
            '<a href="{}" target="_blank" '
            'style="color:#1d4ed8;text-decoration:underline;">تحميل ⬇</a>',
            url,
        )

    @admin.action(description='إلغاء الشهادات المحددة')
    def revoke_certificates(self, request, queryset):
        queryset.update(is_valid=False)
