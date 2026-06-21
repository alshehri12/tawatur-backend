from django.urls import path
from .views import (
    CreateTransactionView,
    MyTransactionsView,
    TransactionDetailView,
)

urlpatterns = [
    path('', CreateTransactionView.as_view(), name='transaction-create'),
    path('my/', MyTransactionsView.as_view(), name='transaction-my'),
    path('<uuid:pk>/', TransactionDetailView.as_view(), name='transaction-detail'),
]
