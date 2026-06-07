"""
Base settings shared across all environments (development, production).
Environment-specific overrides live in development.py / production.py.
"""

from pathlib import Path
from datetime import timedelta
from decouple import config

# Root of the Django project (the folder containing manage.py)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ── Security ──────────────────────────────────────────────────────────────────
SECRET_KEY = config('SECRET_KEY')

# Fernet key used to encrypt sensitive fields (IMEI, serial, phone, national ID)
ENCRYPTION_KEY = config('ENCRYPTION_KEY')

# ── Application Definition ────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',  # Enables refresh token revocation on logout
    'corsheaders',

    # Local apps
    'apps.accounts',
    'apps.products',      # Phase 2
    'apps.fraud',         # Phase 2
    'apps.transactions',  # Phase 3
    'apps.certificates',  # Phase 4
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',              # Must be as high as possible
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# ── Custom User Model ─────────────────────────────────────────────────────────
# Must be set before the first migration is ever run
AUTH_USER_MODEL = 'accounts.User'

# ── Internationalization ──────────────────────────────────────────────────────
LANGUAGE_CODE = 'ar'           # Arabic as platform language
TIME_ZONE = 'Asia/Riyadh'      # Saudi Arabia timezone
USE_I18N = True
USE_TZ = True

# ── Static Files ──────────────────────────────────────────────────────────────
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Django REST Framework ─────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    # Global throttle classes — specific views can override with stricter limits
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '200/hour',
        'user': '2000/hour',
        'otp': '5/hour',         # Strict: max 5 OTP requests per hour per IP
    },
    # Return consistent JSON errors (not HTML 500 pages) when DEBUG=False
    'EXCEPTION_HANDLER': 'rest_framework.views.exception_handler',
}

# ── JWT Configuration ─────────────────────────────────────────────────────────
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),    # Short-lived access token
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),       # Long-lived refresh token
    'ROTATE_REFRESH_TOKENS': True,                     # Issue new refresh token on each refresh
    'BLACKLIST_AFTER_ROTATION': True,                  # Revoke old refresh token immediately
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# ── Redis Cache ───────────────────────────────────────────────────────────────
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://127.0.0.1:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
        },
        'KEY_PREFIX': 'tawatur',
    }
}

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = config('REDIS_URL', default='redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = config('REDIS_URL', default='redis://127.0.0.1:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Riyadh'

# ── OTP Settings ──────────────────────────────────────────────────────────────
OTP_EXPIRY_MINUTES = 5          # OTP expires after 5 minutes
OTP_MAX_ATTEMPTS = 3            # Lock out after 3 wrong attempts
OTP_LOCKOUT_HOURS = 1           # Lockout duration after exceeding attempts
OTP_RATE_LIMIT_PER_HOUR = 5    # Max OTP requests per phone per hour

# ── CORS ──────────────────────────────────────────────────────────────────────
# In production: restrict to known mobile app domains / API gateway only
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []
