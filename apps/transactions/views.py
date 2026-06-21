"""
Transactions API views.

Endpoints (all under /api/v1/transactions/):
  POST  /           → buyer completes a direct purchase (immediately APPROVED)
  GET   /my/        → all transactions where I am the buyer
  GET   /{id}/      → full transaction detail
"""

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import IsVerifiedUser
from .models import Transaction
from .serializers import (
    CreateDirectPurchaseSerializer,
    TransactionSerializer,
    TransactionDetailSerializer,
)
from .services import TransactionService


# ── Create direct purchase ────────────────────────────────────────────────────

class CreateTransactionView(APIView):
    """
    POST /api/v1/transactions/

    Body: { product_id, seller_full_name, seller_id_number, seller_mobile,
            seller_city, price?, device_condition?, seller_terms?, notes? }

    The buyer must be the current registered owner of the product.
    Transaction is immediately APPROVED and a certificate is generated.
    """
    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def post(self, request):
        serializer = CreateDirectPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            txn = TransactionService.create_direct_purchase(
                buyer=request.user,
                product_id=d['product_id'],
                seller_full_name=d['seller_full_name'],
                seller_id_number=d['seller_id_number'],
                seller_mobile=d['seller_mobile'],
                seller_city=d['seller_city'],
                price=d.get('price'),
                device_condition=d.get('device_condition', ''),
                seller_terms=d.get('seller_terms', ''),
                notes=d.get('notes', ''),
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            TransactionDetailSerializer(txn, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


# ── My transactions ───────────────────────────────────────────────────────────

class MyTransactionsView(APIView):
    """GET /api/v1/transactions/my/ — all transactions where the user is the buyer."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        txns = Transaction.objects.select_related('product', 'initiator').filter(
            initiator=request.user
        ).order_by('-created_at')

        return Response(
            TransactionSerializer(txns, many=True, context={'request': request}).data
        )


# ── Transaction detail ────────────────────────────────────────────────────────

class TransactionDetailView(APIView):
    """GET /api/v1/transactions/{id}/ — full detail, buyer only."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            txn = Transaction.objects.select_related('product', 'initiator').get(
                id=pk, initiator=request.user
            )
        except Transaction.DoesNotExist:
            return Response(
                {'detail': 'المعاملة غير موجودة أو ليس لديك صلاحية للوصول إليها.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            TransactionDetailSerializer(txn, context={'request': request}).data
        )
