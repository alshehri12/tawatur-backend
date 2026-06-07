"""
URL patterns for the accounts app.
All routes are mounted under /api/v1/auth/ in config/urls.py.
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    RequestOTPView,
    LoginView,
    RegisterIndividualView,
    RegisterBusinessView,
    SubmitIndividualVerificationView,
    SubmitBusinessVerificationView,
    UserMeView,
    LogoutView,
)

urlpatterns = [
    # ── OTP ───────────────────────────────────────────────────────────────────
    path('request-otp/', RequestOTPView.as_view(), name='auth-request-otp'),

    # ── Login ─────────────────────────────────────────────────────────────────
    path('login/', LoginView.as_view(), name='auth-login'),

    # ── Registration ──────────────────────────────────────────────────────────
    path('register/individual/', RegisterIndividualView.as_view(), name='auth-register-individual'),
    path('register/business/', RegisterBusinessView.as_view(), name='auth-register-business'),

    # ── Identity Verification (mock Absher / Wathiq) ──────────────────────────
    path('verify/individual/', SubmitIndividualVerificationView.as_view(), name='auth-verify-individual'),
    path('verify/business/', SubmitBusinessVerificationView.as_view(), name='auth-verify-business'),

    # ── Profile ───────────────────────────────────────────────────────────────
    path('me/', UserMeView.as_view(), name='auth-me'),

    # ── Token Management ──────────────────────────────────────────────────────
    path('token/refresh/', TokenRefreshView.as_view(), name='auth-token-refresh'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
]
