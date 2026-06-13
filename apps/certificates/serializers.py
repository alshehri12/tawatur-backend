from rest_framework import serializers
from .models import Certificate


class CertificateSerializer(serializers.ModelSerializer):
    certificate_type_display = serializers.CharField(source='get_certificate_type_display', read_only=True)
    pdf_url = serializers.SerializerMethodField()
    qr_code_url = serializers.SerializerMethodField()
    product_summary = serializers.SerializerMethodField()

    def _absolute(self, path: str) -> str:
        if not path:
            return ''
        request = self.context.get('request')
        url = f'/media/{path}'
        return request.build_absolute_uri(url) if request else url

    def get_pdf_url(self, obj):
        return self._absolute(obj.pdf_path)

    def get_qr_code_url(self, obj):
        return self._absolute(obj.qr_code_path)

    class Meta:
        model = Certificate
        fields = [
            'id',
            'certificate_number',
            'certificate_type', 'certificate_type_display',
            'is_valid',
            'verification_url',
            'qr_code_url',
            'pdf_url',
            'product_summary',
            'issued_at',
        ]

    def get_product_summary(self, obj):
        return {
            'id': str(obj.product.id),
            'brand': obj.product.brand,
            'model': obj.product.model,
            'category_display': obj.product.get_category_display(),
            'trust_score': obj.product.trust_score,
            'trust_level': obj.product.trust_level,
        }


class CertificateVerifySerializer(serializers.Serializer):
    """Response for the public /api/v1/verify/{number}/ endpoint."""
    certificate_number = serializers.CharField()
    certificate_type_display = serializers.CharField()
    is_valid = serializers.BooleanField()
    issued_at = serializers.DateTimeField()
    product = serializers.DictField()
    verification_message = serializers.CharField()
