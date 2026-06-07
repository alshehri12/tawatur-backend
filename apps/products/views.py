"""
Products API views.

Endpoints (all under /api/v1/products/):
  POST  /                          → register a new product (verified users only)
  GET   /my/                       → products owned by the current user
  GET   /lookup/                   → find a product by IMEI or serial (?imei= or ?serial=)
  GET   /{id}/                     → product detail (owner gets full view, others get public)
  GET   /{id}/ownership-history/   → public ownership chain summary (no personal data)
  GET   /{id}/trust-score/         → trust score breakdown
"""

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import IsVerifiedUser
from .models import Product, OwnershipRecord
from .serializers import (
    CreateProductSerializer,
    ProductPublicSerializer,
    ProductOwnerSerializer,
    OwnershipHistorySummarySerializer,
    TrustScoreSerializer,
)
from .services import ProductRegistrationService, TrustScoreService


# ── Register Product ──────────────────────────────────────────────────────────

class CreateProductView(APIView):
    """
    POST /api/v1/products/

    Creates a new product and its initial OwnershipRecord.
    Requires identity verification (IsVerifiedUser).
    """
    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def post(self, request):
        serializer = CreateProductSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product = ProductRegistrationService.register(
            user=request.user,
            validated_data=serializer.validated_data,
        )

        return Response(
            ProductOwnerSerializer(product).data,
            status=status.HTTP_201_CREATED,
        )


# ── My Products ───────────────────────────────────────────────────────────────

class MyProductsView(APIView):
    """GET /api/v1/products/my/ — list all products the current user owns right now."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Find products where the user has an active ownership record
        product_ids = OwnershipRecord.objects.filter(
            owner=request.user,
            is_current=True,
        ).values_list('product_id', flat=True)

        products = Product.objects.filter(id__in=product_ids, is_active=True)
        return Response(ProductOwnerSerializer(products, many=True).data)


# ── Product Lookup ────────────────────────────────────────────────────────────

class ProductLookupView(APIView):
    """
    GET /api/v1/products/lookup/?imei=XXXXXXXX
    GET /api/v1/products/lookup/?serial=XXXXXXXX

    Find a product by IMEI or serial number. Used by businesses before
    creating a purchase transaction to verify the device's history.
    Returns the public view — no encrypted fields.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from core.hashing import hash_value

        imei = request.query_params.get('imei', '').strip()
        serial = request.query_params.get('serial', '').strip()

        if not imei and not serial:
            return Response(
                {'detail': 'يجب إدخال IMEI أو الرقم التسلسلي للبحث.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        product = None

        if imei:
            imei_hash = hash_value(imei)
            product = (
                Product.objects.filter(imei_1_hash=imei_hash, is_active=True).first()
                or Product.objects.filter(imei_2_hash=imei_hash, is_active=True).first()
            )

        if not product and serial:
            serial_hash = hash_value(serial)
            product = Product.objects.filter(serial_hash=serial_hash, is_active=True).first()

        if not product:
            return Response(
                {'detail': 'لم يتم العثور على منتج مسجل بهذا المعرّف.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(ProductPublicSerializer(product).data)


# ── Product Detail ────────────────────────────────────────────────────────────

class ProductDetailView(APIView):
    """
    GET /api/v1/products/{id}/

    Returns full details for the current owner, public details for everyone else.
    """
    permission_classes = [IsAuthenticated]

    def _get_product(self, pk):
        try:
            return Product.objects.get(id=pk, is_active=True)
        except Product.DoesNotExist:
            return None

    def _is_current_owner(self, user, product) -> bool:
        return OwnershipRecord.objects.filter(
            product=product, owner=user, is_current=True
        ).exists()

    def get(self, request, pk):
        product = self._get_product(pk)
        if not product:
            return Response({'detail': 'المنتج غير موجود.'}, status=status.HTTP_404_NOT_FOUND)

        if self._is_current_owner(request.user, product):
            serializer = ProductOwnerSerializer(product)
        else:
            serializer = ProductPublicSerializer(product)

        return Response(serializer.data)


# ── Ownership History ─────────────────────────────────────────────────────────

class OwnershipHistoryView(APIView):
    """
    GET /api/v1/products/{id}/ownership-history/

    Public — accessible to any authenticated user.
    Returns chain statistics and a timeline with no owner identities.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            product = Product.objects.get(id=pk, is_active=True)
        except Product.DoesNotExist:
            return Response({'detail': 'المنتج غير موجود.'}, status=status.HTTP_404_NOT_FOUND)

        records = product.ownership_records.select_related('owner').order_by('start_date')

        first_record = records.first()
        last_record = records.last()

        trust_level_labels = {
            'excellent': 'ممتاز', 'high': 'عالٍ',
            'medium': 'متوسط', 'low': 'منخفض',
        }

        from .serializers import OwnershipRecordPublicSerializer
        summary = {
            'total_owners': records.count(),
            'first_recorded_date': first_record.start_date if first_record else None,
            'latest_transfer_date': last_record.start_date if last_record else None,
            'chain_integrity': product.chain_integrity,
            'verified_transfer_count': records.filter(owner__identity_submitted=True).count(),
            'trust_score': product.trust_score,
            'trust_level': product.trust_level,
            'trust_level_display': trust_level_labels.get(product.trust_level, ''),
            'timeline': OwnershipRecordPublicSerializer(records, many=True).data,
        }

        serializer = OwnershipHistorySummarySerializer(data=summary)
        serializer.is_valid()   # Already valid — built from DB values
        return Response(serializer.data)


# ── Trust Score ───────────────────────────────────────────────────────────────

class TrustScoreView(APIView):
    """
    GET /api/v1/products/{id}/trust-score/

    Returns the current trust score with a breakdown of contributing factors.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            product = Product.objects.get(id=pk, is_active=True)
        except Product.DoesNotExist:
            return Response({'detail': 'المنتج غير موجود.'}, status=status.HTTP_404_NOT_FOUND)

        records = product.ownership_records.select_related('owner').all()
        verified_count = records.filter(owner__identity_submitted=True).count()

        from apps.fraud.models import FraudAlert
        active_alerts = FraudAlert.objects.filter(product=product, status=FraudAlert.OPEN).count()

        trust_level_labels = {
            'excellent': 'ممتاز', 'high': 'عالٍ',
            'medium': 'متوسط', 'low': 'منخفض',
        }

        breakdown = {
            'base_score': 50,
            'verified_transfers_bonus': min(verified_count, 3) * 10,
            'chain_integrity_bonus': 10 if product.chain_integrity == 100 else 0,
            'fraud_alert_penalty': active_alerts * -20,
            'verified_owners': verified_count,
            'active_fraud_alerts': active_alerts,
        }

        data = {
            'trust_score': product.trust_score,
            'trust_level': product.trust_level,
            'trust_level_display': trust_level_labels.get(product.trust_level, ''),
            'chain_integrity': product.chain_integrity,
            'breakdown': breakdown,
        }

        return Response(TrustScoreSerializer(data).data)
