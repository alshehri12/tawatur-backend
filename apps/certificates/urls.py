from django.urls import path
from .views import (
    MyCertificatesView,
    SoldByMeCertificatesView,
    GenerateCertificateView,
    CertificateDetailView,
    CertificatePDFView,
    VerifyCertificateView,
)

certificates_urlpatterns = [
    path('', MyCertificatesView.as_view(), name='certificate-list'),
    path('sold-by-me/', SoldByMeCertificatesView.as_view(), name='certificate-sold-by-me'),
    path('generate/', GenerateCertificateView.as_view(), name='certificate-generate'),
    path('<uuid:pk>/', CertificateDetailView.as_view(), name='certificate-detail'),
    path('<uuid:pk>/pdf/', CertificatePDFView.as_view(), name='certificate-pdf'),
]

# Mounted separately at /api/v1/verify/ in config/urls.py
verify_urlpatterns = [
    path('<str:certificate_number>/', VerifyCertificateView.as_view(), name='certificate-verify'),
]
