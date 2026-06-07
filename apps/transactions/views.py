"""
Transactions API views.

Endpoints (all under /api/v1/transactions/):
  POST  /                       → create a transfer request
  GET   /my/                    → transactions where I am initiator or recipient
  GET   /{id}/                  → full transaction detail (parties only)
  POST  /{id}/approve/          → recipient approves → ownership transferred
  POST  /{id}/reject/           → recipient rejects
  POST  /{id}/cancel/           → initiator cancels
  GET   /link/{token}/          → resolve a share link (public — no auth needed)
"""

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db.models import Q

from apps.accounts.permissions import IsVerifiedUser
from .models import Transaction
from .serializers import (
    CreateTransactionSerializer,
    TransactionSerializer,
    TransactionDetailSerializer,
)
from .services import TransactionService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_transaction_for_party(pk, user):
    """
    Return the transaction only if the requesting user is one of the two parties.
    Returns None if not found or not a party.
    """
    try:
        return Transaction.objects.select_related(
            'product', 'initiator', 'recipient'
        ).get(
            Q(initiator=user) | Q(recipient=user),
            id=pk,
        )
    except Transaction.DoesNotExist:
        return None


# ── Create ────────────────────────────────────────────────────────────────────

class CreateTransactionView(APIView):
    """
    POST /api/v1/transactions/

    Body: { product_id, recipient_phone, transaction_type, price?, notes? }

    The initiator must be the current owner of the product and identity-verified.
    """
    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def post(self, request):
        serializer = CreateTransactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            txn = TransactionService.create(
                initiator=request.user,
                product_id=serializer.validated_data['product_id'],
                recipient_phone=serializer.validated_data['recipient_phone'],
                transaction_type=serializer.validated_data['transaction_type'],
                price=serializer.validated_data.get('price'),
                notes=serializer.validated_data.get('notes', ''),
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            TransactionDetailSerializer(txn, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


# ── My Transactions ───────────────────────────────────────────────────────────

class MyTransactionsView(APIView):
    """
    GET /api/v1/transactions/my/

    Returns all transactions where the current user is initiator OR recipient,
    ordered by newest first.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        txns = Transaction.objects.select_related(
            'product', 'initiator', 'recipient'
        ).filter(
            Q(initiator=request.user) | Q(recipient=request.user)
        ).order_by('-created_at')

        return Response(
            TransactionSerializer(txns, many=True, context={'request': request}).data
        )


# ── Transaction Detail ────────────────────────────────────────────────────────

class TransactionDetailView(APIView):
    """
    GET /api/v1/transactions/{id}/

    Full transaction detail, including audit log.
    Only accessible to the two parties involved.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        txn = _get_transaction_for_party(pk, request.user)
        if not txn:
            return Response(
                {'detail': 'المعاملة غير موجودة أو ليس لديك صلاحية للوصول إليها.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            TransactionDetailSerializer(txn, context={'request': request}).data
        )


# ── Approve ───────────────────────────────────────────────────────────────────

class ApproveTransactionView(APIView):
    """
    POST /api/v1/transactions/{id}/approve/

    Recipient approves the transfer → ownership is immediately transferred.
    """
    permission_classes = [IsAuthenticated, IsVerifiedUser]

    def post(self, request, pk):
        txn = _get_transaction_for_party(pk, request.user)
        if not txn:
            return Response(
                {'detail': 'المعاملة غير موجودة.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            txn = TransactionService.approve(txn, actor=request.user)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'detail': 'تمت عملية نقل الملكية بنجاح.',
            'transaction': TransactionDetailSerializer(txn, context={'request': request}).data,
        })


# ── Reject ────────────────────────────────────────────────────────────────────

class RejectTransactionView(APIView):
    """POST /api/v1/transactions/{id}/reject/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        txn = _get_transaction_for_party(pk, request.user)
        if not txn:
            return Response({'detail': 'المعاملة غير موجودة.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            txn = TransactionService.reject(txn, actor=request.user)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'detail': 'تم رفض طلب نقل الملكية.'})


# ── Cancel ────────────────────────────────────────────────────────────────────

class CancelTransactionView(APIView):
    """POST /api/v1/transactions/{id}/cancel/"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        txn = _get_transaction_for_party(pk, request.user)
        if not txn:
            return Response({'detail': 'المعاملة غير موجودة.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            txn = TransactionService.cancel(txn, actor=request.user)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'detail': 'تم إلغاء المعاملة.'})


# ── Resolve Share Link ────────────────────────────────────────────────────────

class ResolveLinkView(APIView):
    """
    GET /api/v1/transactions/link/{token}/

    Public endpoint — no auth required.
    Used when the recipient taps the WhatsApp/SMS link on their phone.

    If the user is not logged in, the app intercepts this and redirects
    to the login screen, then back to the transaction.
    If logged in, returns the transaction detail.
    """
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            txn = Transaction.objects.select_related(
                'product', 'initiator', 'recipient'
            ).get(link_token=token)
        except Transaction.DoesNotExist:
            return Response(
                {'detail': 'رابط المعاملة غير صالح أو منتهي الصلاحية.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Return minimal public info — enough for the app to decide what to show
        return Response({
            'transaction_id': str(txn.id),
            'status': txn.status,
            'product': {
                'brand': txn.product.brand,
                'model': txn.product.model,
                'category_display': txn.product.get_category_display(),
                'trust_score': txn.product.trust_score,
                'trust_level': txn.product.trust_level,
            },
            'transaction_type_display': txn.get_transaction_type_display(),
            'price': txn.price,
            'expires_at': txn.expires_at,
            'requires_auth': not request.user.is_authenticated,
        })
