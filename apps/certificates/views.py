"""
Certificates API views.

Endpoints:
  GET   /api/v1/certificates/                  → list my certificates
  POST  /api/v1/certificates/generate/         → generate on-demand ownership cert
  GET   /api/v1/certificates/{id}/             → certificate detail
  GET   /api/v1/certificates/{id}/pdf/         → download PDF (streams the file)
  GET   /api/v1/verify/{certificate_number}/   → public verification (no auth)
"""

import os
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny

from .models import Certificate
from .serializers import CertificateSerializer, CertificateVerifySerializer
from .services import CertificateService


class MyCertificatesView(APIView):
    """GET /api/v1/certificates/ — all certificates issued to the current user."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        certs = Certificate.objects.filter(owner=request.user).select_related('product')
        return Response(CertificateSerializer(certs, many=True, context={'request': request}).data)


class GenerateCertificateView(APIView):
    """
    POST /api/v1/certificates/generate/

    Body: { product_id: '<uuid>' }

    Generates a Current Ownership Certificate on demand.
    The requesting user must be the current owner of the product.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        product_id = request.data.get('product_id')
        if not product_id:
            return Response({'detail': 'product_id مطلوب.'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.products.models import Product
        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            return Response({'detail': 'المنتج غير موجود.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            cert = CertificateService.generate_ownership_certificate(request.user, product)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_403_FORBIDDEN)

        return Response(
            CertificateSerializer(cert, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class CertificateDetailView(APIView):
    """GET /api/v1/certificates/{id}/ — detail for owner only."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            cert = Certificate.objects.get(id=pk, owner=request.user)
        except Certificate.DoesNotExist:
            return Response({'detail': 'الشهادة غير موجودة.'}, status=status.HTTP_404_NOT_FOUND)

        return Response(CertificateSerializer(cert, context={'request': request}).data)


class CertificatePDFView(APIView):
    """
    GET /api/v1/certificates/{id}/pdf/

    Streams the PDF file directly to the client.
    Only the certificate owner can download it.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            cert = Certificate.objects.get(id=pk, owner=request.user)
        except Certificate.DoesNotExist:
            return Response({'detail': 'الشهادة غير موجودة.'}, status=status.HTTP_404_NOT_FOUND)

        if not cert.pdf_path:
            return Response({'detail': 'ملف PDF غير متاح بعد.'}, status=status.HTTP_404_NOT_FOUND)

        pdf_full_path = Path(settings.MEDIA_ROOT) / cert.pdf_path
        if not pdf_full_path.exists():
            return Response({'detail': 'ملف PDF غير موجود.'}, status=status.HTTP_404_NOT_FOUND)

        response = FileResponse(
            open(pdf_full_path, 'rb'),
            content_type='application/pdf',
        )
        response['Content-Disposition'] = f'attachment; filename="{cert.certificate_number}.pdf"'
        return response


class VerifyCertificateView(APIView):
    """
    GET /api/v1/verify/{certificate_number}/

    Public endpoint — no authentication required.
    Used by anyone who scans the QR code on a physical or digital certificate.
    """
    permission_classes = [AllowAny]

    def get(self, request, certificate_number):
        try:
            cert = Certificate.objects.select_related('product').get(
                certificate_number=certificate_number.upper()
            )
        except Certificate.DoesNotExist:
            return Response(
                {'detail': 'رقم الشهادة غير صالح أو غير موجود في قاعدة البيانات.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        trust_labels = {'excellent': 'ممتاز', 'high': 'عالٍ', 'medium': 'متوسط', 'low': 'منخفض'}

        data = {
            'certificate_number': cert.certificate_number,
            'certificate_type_display': cert.get_certificate_type_display(),
            'is_valid': cert.is_valid,
            'issued_at': cert.issued_at,
            'product': {
                'brand': cert.product.brand,
                'model': cert.product.model,
                'category_display': cert.product.get_category_display(),
                'trust_score': cert.product.trust_score,
                'trust_level_display': trust_labels.get(cert.product.trust_level, ''),
                'chain_integrity': cert.product.chain_integrity,
                'total_owners': cert.product.ownership_records.count(),
            },
            'verification_message': (
                'هذه الشهادة صالحة وموثقة على منصة تواتر.'
                if cert.is_valid else
                'هذه الشهادة ملغاة أو غير صالحة.'
            ),
        }

        return Response(CertificateVerifySerializer(data).data)
