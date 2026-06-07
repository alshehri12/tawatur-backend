from django.urls import path
from .views import (
    CreateTransactionView,
    MyTransactionsView,
    TransactionDetailView,
    ApproveTransactionView,
    RejectTransactionView,
    CancelTransactionView,
    ResolveLinkView,
)

urlpatterns = [
    # Collection
    path('', CreateTransactionView.as_view(), name='transaction-create'),
    path('my/', MyTransactionsView.as_view(), name='transaction-my'),

    # Share link (public — no auth)
    path('link/<uuid:token>/', ResolveLinkView.as_view(), name='transaction-link'),

    # Single transaction
    path('<uuid:pk>/', TransactionDetailView.as_view(), name='transaction-detail'),
    path('<uuid:pk>/approve/', ApproveTransactionView.as_view(), name='transaction-approve'),
    path('<uuid:pk>/reject/', RejectTransactionView.as_view(), name='transaction-reject'),
    path('<uuid:pk>/cancel/', CancelTransactionView.as_view(), name='transaction-cancel'),
]
