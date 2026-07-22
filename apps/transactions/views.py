"""
Transactions API views.

Endpoints (all under /api/v1/transactions/):
  POST  /                    → buyer completes a direct purchase (immediately APPROVED)
  GET   /my/                 → all transactions where I am the buyer
  GET   /{id}/               → full transaction detail (buyer OR matched seller)
  GET   /pending-for-me/     → buy-requests addressed to my phone number, awaiting my response
  POST  /{id}/seller-respond/ → accept/reject a request addressed to my phone number
"""

from django.db.models import Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.accounts.permissions import IsVerifiedUser
from .models import Transaction
from .serializers import (
    CreateDirectPurchaseSerializer,
    CreateRegisteredPurchaseSerializer,
    TransactionSerializer,
    TransactionDetailSerializer,
)
from .services import TransactionService


# ── Register + document a purchase in one step ───────────────────────────────

class CreateRegisteredPurchaseView(APIView):
    """
    POST /api/v1/transactions/register-purchase/

    Body: { category, brand, model, condition, imei_1?, imei_2?, serial_number?,
            product_notes?, seller_full_name, seller_id_number, seller_mobile,
            seller_city, price?, seller_terms?, notes? }

    Registers the device AND documents the purchase in a single call —
    replaces the separate "register a product" flow that used to end at
    "منتجاتي" with nothing else happening. The transaction is created
    PENDING — the buyer shares confirm_url (in the response) with the
    seller, who reviews the deal and accepts/rejects it without needing a
    platform account. A certificate is generated only once the seller
    confirms.
    """
    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def post(self, request):
        serializer = CreateRegisteredPurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        product_data = {
            'category':      d['category'],
            'brand':         d['brand'],
            'model':         d['model'],
            'condition':     d['condition'],
            'imei_1':        d.get('imei_1', ''),
            'imei_2':        d.get('imei_2', ''),
            'serial_number': d.get('serial_number', ''),
            'notes':         d.get('product_notes', ''),
        }

        txn = TransactionService.create_registered_purchase(
            buyer=request.user,
            product_data=product_data,
            seller_full_name=d['seller_full_name'],
            seller_id_number=d['seller_id_number'],
            seller_mobile=d['seller_mobile'],
            seller_city=d['seller_city'],
            price=d.get('price'),
            seller_terms=d.get('seller_terms', ''),
            notes=d.get('notes', ''),
        )

        return Response(
            TransactionDetailSerializer(txn, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


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
    """
    GET /api/v1/transactions/{id}/

    Full detail — accessible to the buyer (initiator), OR to a user whose
    account phone number matches the seller_mobile entered on the
    transaction (i.e. the named seller, once they've registered).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            txn = Transaction.objects.select_related('product', 'initiator').get(
                Q(initiator=request.user) | Q(seller_mobile_hash=request.user.phone_hash),
                id=pk,
            )
        except Transaction.DoesNotExist:
            return Response(
                {'detail': 'المعاملة غير موجودة أو ليس لديك صلاحية للوصول إليها.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            TransactionDetailSerializer(txn, context={'request': request}).data
        )


# ── Pending requests addressed to my phone number (as the named seller) ──────

class PendingSellerRequestsView(APIView):
    """
    GET /api/v1/transactions/pending-for-me/

    Buy-requests where I'm named as the seller (by phone number) and the
    request is still pending my response. Only meaningful once I've
    registered a Tawatur account with the same phone number the buyer
    entered — matched via seller_mobile_hash == my phone_hash.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        txns = Transaction.objects.select_related('product', 'initiator').filter(
            seller_mobile_hash=request.user.phone_hash,
            status=Transaction.PENDING,
        ).order_by('-created_at')

        return Response(
            TransactionSerializer(txns, many=True, context={'request': request}).data
        )


# ── Seller responds in-app (accept/reject) ────────────────────────────────────

class SellerRespondView(APIView):
    """
    POST /api/v1/transactions/{id}/seller-respond/

    Body: { action: 'accept' | 'reject' }

    In-app equivalent of the public confirm link — only usable by the
    account whose phone number matches seller_mobile_hash on the
    transaction. Same underlying service methods as the public link, so
    behavior (certificate generation, trust score) is identical either way.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            txn = Transaction.objects.select_related('product', 'initiator').get(
                id=pk, seller_mobile_hash=request.user.phone_hash,
            )
        except Transaction.DoesNotExist:
            return Response(
                {'detail': 'هذا الطلب غير موجّه إلى رقم جوالك.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        action = request.data.get('action')
        try:
            if action == 'accept':
                TransactionService.confirm_by_seller(txn)
            elif action == 'reject':
                TransactionService.reject_by_seller(txn)
            else:
                return Response({'detail': 'action يجب أن يكون accept أو reject.'},
                                 status=status.HTTP_400_BAD_REQUEST)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        txn.refresh_from_db()
        return Response(
            TransactionDetailSerializer(txn, context={'request': request}).data
        )
