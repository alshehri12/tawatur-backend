"""
Authentication & account management API views.

Endpoints (all under /api/v1/auth/):
  POST  request-otp/              → send OTP to a phone number
  POST  login/                    → exchange phone + OTP for JWT tokens
  POST  register/individual/      → create individual account
  POST  register/business/        → create business account
  POST  verify/individual/        → submit identity docs (mock Absher)
  POST  verify/business/          → submit CR number (mock Wathiq)
  GET   me/                       → current user profile
  POST  token/refresh/            → rotate JWT tokens
  POST  logout/                   → blacklist refresh token
"""

from django.db import transaction
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.views import TokenRefreshView

from .models import User
from .serializers import (
    RequestOTPSerializer,
    VerifyOTPSerializer,
    RegisterIndividualSerializer,
    RegisterBusinessSerializer,
    SubmitIndividualVerificationSerializer,
    SubmitBusinessVerificationSerializer,
    UserProfileSerializer,
)
from .services import OTPService, IdentityVerificationService


# ── Custom Throttle ───────────────────────────────────────────────────────────

class OTPRequestThrottle(SimpleRateThrottle):
    """
    Stricter throttle applied only to the OTP request endpoint.
    Rate is set in settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['otp'].
    """
    scope = 'otp'

    def get_cache_key(self, request, view):
        # Throttle by client IP (not by user, since the user isn't authenticated yet)
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


# ── Helper ────────────────────────────────────────────────────────────────────

def _token_pair(user: User) -> dict:
    """Return a dict with access + refresh JWT tokens for the given user."""
    refresh = RefreshToken.for_user(user)
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    }


def _update_device_fingerprint(user: User, request) -> None:
    """Hash and store the caller's User-Agent + IP as a device fingerprint."""
    from core.hashing import hash_value
    ua = request.META.get('HTTP_USER_AGENT', '')
    ip = request.META.get('REMOTE_ADDR', '')
    user.device_fingerprint_hash = hash_value(f'{ua}{ip}')
    user.save(update_fields=['device_fingerprint_hash'])


# ── OTP Request ───────────────────────────────────────────────────────────────

class RequestOTPView(APIView):
    """
    POST /api/v1/auth/request-otp/

    Body: { phone_number, purpose: 'login'|'register' }

    Generates a 6-digit OTP and (in development) returns it in the response.
    In production the OTP would be dispatched via SMS/WhatsApp — that
    integration is added in Phase 3.
    """
    permission_classes = [AllowAny]
    throttle_classes = [OTPRequestThrottle]

    def post(self, request):
        serializer = RequestOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        purpose = serializer.validated_data['purpose']

        otp_plain, success = OTPService.request_otp(phone_number, purpose)

        if not success:
            return Response(
                {'detail': 'تم تجاوز الحد المسموح لطلبات رمز التحقق. حاول مرة أخرى لاحقاً.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        response_data = {'detail': 'تم إرسال رمز التحقق إلى جوالك.'}

        # Expose plain OTP only in development — never in production
        if getattr(settings, 'OTP_EXPOSE_IN_RESPONSE', False):
            response_data['otp'] = otp_plain

        return Response(response_data, status=status.HTTP_200_OK)


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginView(APIView):
    """
    POST /api/v1/auth/login/

    Body: { phone_number, otp, purpose: 'login' }

    Verifies the OTP, finds the user, and returns a JWT token pair + profile.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        otp = serializer.validated_data['otp']

        # Validate OTP before touching the User table
        verified, error = OTPService.verify_otp(phone_number, otp, 'login')
        if not verified:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        # Locate the user by phone hash
        from core.hashing import hash_phone
        try:
            user = User.objects.get(phone_hash=hash_phone(phone_number))
        except User.DoesNotExist:
            return Response(
                {'detail': 'لا يوجد حساب مرتبط بهذا الرقم. يرجى إنشاء حساب أولاً.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not user.is_active:
            return Response(
                {'detail': 'حسابك موقوف. يرجى التواصل مع الدعم.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        _update_device_fingerprint(user, request)

        return Response({
            'detail': 'تم تسجيل الدخول بنجاح.',
            **_token_pair(user),
            'user': UserProfileSerializer(user).data,
        })


# ── Individual Registration ───────────────────────────────────────────────────

class RegisterIndividualView(APIView):
    """
    POST /api/v1/auth/register/individual/

    Body: { phone_number, otp, national_id?, iqama? }

    Creates a new individual account and submits identity data in one step.
    The phone number must not already be registered.
    """
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = RegisterIndividualSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        otp = serializer.validated_data['otp']

        # Verify OTP first — do not create a user if the OTP is wrong
        verified, error = OTPService.verify_otp(phone_number, otp, 'register')
        if not verified:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        # Prevent duplicate accounts
        from core.hashing import hash_phone
        if User.objects.filter(phone_hash=hash_phone(phone_number)).exists():
            return Response(
                {'detail': 'هذا الرقم مسجل بالفعل. يمكنك تسجيل الدخول مباشرةً.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Create user (manager handles hashing + encryption)
        user = User.objects.create_user(
            phone_number=phone_number,
            user_type=User.INDIVIDUAL,
        )

        # Submit identity verification (mock Absher)
        IdentityVerificationService.verify_individual(
            user,
            national_id=serializer.validated_data.get('national_id') or None,
            iqama=serializer.validated_data.get('iqama') or None,
            full_name=serializer.validated_data.get('full_name') or None,
        )

        _update_device_fingerprint(user, request)

        return Response({
            'detail': 'تم إنشاء حسابك بنجاح. سيتم التحقق من هويتك قريباً.',
            **_token_pair(user),
            'user': UserProfileSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


# ── Business Registration ─────────────────────────────────────────────────────

class RegisterBusinessView(APIView):
    """
    POST /api/v1/auth/register/business/

    Body: { phone_number, otp, cr_number, business_name }

    Creates a new business account and submits CR data in one step.
    """
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = RegisterBusinessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        otp = serializer.validated_data['otp']

        verified, error = OTPService.verify_otp(phone_number, otp, 'register')
        if not verified:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        from core.hashing import hash_phone
        if User.objects.filter(phone_hash=hash_phone(phone_number)).exists():
            return Response(
                {'detail': 'هذا الرقم مسجل بالفعل.'},
                status=status.HTTP_409_CONFLICT,
            )

        user = User.objects.create_user(
            phone_number=phone_number,
            user_type=User.BUSINESS,
        )

        # Submit business verification (mock Wathiq)
        IdentityVerificationService.verify_business(
            user,
            cr_number=serializer.validated_data['cr_number'],
            business_name=serializer.validated_data['business_name'],
        )

        _update_device_fingerprint(user, request)

        return Response({
            'detail': 'تم إنشاء حساب منشأتك بنجاح. سيتم التحقق من السجل التجاري قريباً.',
            **_token_pair(user),
            'user': UserProfileSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


# ── Post-Registration Verification ───────────────────────────────────────────

class SubmitIndividualVerificationView(APIView):
    """
    POST /api/v1/auth/verify/individual/

    Allows a logged-in individual user to submit (or re-submit) their ID.
    Useful if they skipped the step during registration.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.user_type != User.INDIVIDUAL:
            return Response(
                {'detail': 'هذا الإجراء مخصص للأفراد فقط.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SubmitIndividualVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        success, error = IdentityVerificationService.verify_individual(
            request.user,
            national_id=serializer.validated_data.get('national_id') or None,
            iqama=serializer.validated_data.get('iqama') or None,
            full_name=serializer.validated_data.get('full_name') or None,
        )

        if not success:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'detail': 'تم استلام بيانات التحقق. سيتم مراجعتها قريباً.',
            'verification_status': request.user.verification_status,
        })


class SubmitBusinessVerificationView(APIView):
    """
    POST /api/v1/auth/verify/business/

    Allows a logged-in business user to submit (or update) their CR data.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.user_type != User.BUSINESS:
            return Response(
                {'detail': 'هذا الإجراء مخصص للجهات التجارية فقط.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SubmitBusinessVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        success, error = IdentityVerificationService.verify_business(
            request.user,
            cr_number=serializer.validated_data['cr_number'],
            business_name=serializer.validated_data['business_name'],
        )

        if not success:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'detail': 'تم استلام بيانات السجل التجاري. سيتم مراجعتها قريباً.',
            'verification_status': request.user.verification_status,
        })


# ── Profile ───────────────────────────────────────────────────────────────────

class UserMeView(RetrieveAPIView):
    """GET /api/v1/auth/me/ — return the authenticated user's profile."""
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_object(self):
        return self.request.user


# ── Logout ────────────────────────────────────────────────────────────────────

class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/

    Body: { refresh: '<refresh_token>' }

    Blacklists the refresh token so it cannot be used to issue new access tokens.
    The current access token remains valid until its 15-minute TTL expires —
    clients should discard it immediately.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'detail': 'refresh token مطلوب.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response(
                {'detail': 'رمز التحديث غير صالح أو منتهي الصلاحية.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({'detail': 'تم تسجيل الخروج بنجاح.'})
