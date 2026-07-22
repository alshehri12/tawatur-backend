from django.urls import path
from .views import (
    CreateTransactionView,
    CreateRegisteredPurchaseView,
    MyTransactionsView,
    TransactionDetailView,
    PendingSellerRequestsView,
    SellerRespondView,
)

urlpatterns = [
    path('', CreateTransactionView.as_view(), name='transaction-create'),
    path('register-purchase/', CreateRegisteredPurchaseView.as_view(), name='transaction-register-purchase'),
    path('my/', MyTransactionsView.as_view(), name='transaction-my'),
    path('pending-for-me/', PendingSellerRequestsView.as_view(), name='transaction-pending-for-me'),
    path('<uuid:pk>/', TransactionDetailView.as_view(), name='transaction-detail'),
    path('<uuid:pk>/seller-respond/', SellerRespondView.as_view(), name='transaction-seller-respond'),
]
