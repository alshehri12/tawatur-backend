from django.urls import path
from .views import (
    CreateProductView,
    MyProductsView,
    ProductLookupView,
    ProductDetailView,
    OwnershipHistoryView,
    TrustScoreView,
)

urlpatterns = [
    # Collection
    path('', CreateProductView.as_view(), name='product-create'),
    path('my/', MyProductsView.as_view(), name='product-my'),
    path('lookup/', ProductLookupView.as_view(), name='product-lookup'),

    # Single product
    path('<uuid:pk>/', ProductDetailView.as_view(), name='product-detail'),
    path('<uuid:pk>/ownership-history/', OwnershipHistoryView.as_view(), name='product-ownership-history'),
    path('<uuid:pk>/trust-score/', TrustScoreView.as_view(), name='product-trust-score'),
]
