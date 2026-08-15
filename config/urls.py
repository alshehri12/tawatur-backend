"""
Root URL configuration.
Each app registers its own urls.py under /api/v1/<app>/.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from apps.certificates.urls import certificates_urlpatterns, verify_urlpatterns
from apps.transactions.public_views import seller_confirm_view, terms_view


def health(request):
    """Lightweight ping — no DB, no cache. Used by the mobile app to verify connectivity."""
    return JsonResponse({'status': 'ok', 'service': 'tawatur'})


urlpatterns = [
    path('admin/', admin.site.urls),

    # ── Health check (no auth, no dependencies) ───────────────────────────────
    path('api/v1/health/', health, name='health'),

    # ── Public seller-confirmation page (opened from a shared link, no login) ─
    path('confirm/<uuid:token>/', seller_confirm_view, name='seller-confirm'),

    # ── Public terms & conditions — linked from the app and the confirm page ──
    path('terms/', terms_view, name='terms'),

    # ── API v1 ────────────────────────────────────────────────────────────────
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/products/', include('apps.products.urls')),
    path('api/v1/transactions/', include('apps.transactions.urls')),
    path('api/v1/certificates/', include(certificates_urlpatterns)),
    path('api/v1/verify/', include(verify_urlpatterns)),      # public QR scan endpoint
]

# Serve media files (certificates, QR codes) in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
