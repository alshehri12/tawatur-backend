"""
Development settings. Extends base.py with local-only overrides.
Never use these settings in production.
"""

from .base import *
from decouple import config

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '192.168.100.8', 'Abdulrahmans-Mac-Studio.local']

# ── Database ──────────────────────────────────────────────────────────────────
# Set USE_POSTGRES=True in .env once PostgreSQL is installed and running.
# Default is SQLite — zero-config, works out of the box for local development.
_use_postgres = config('USE_POSTGRES', default=False, cast=bool)

if _use_postgres:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME', default='tawatur_db'),
            'USER': config('DB_USER', default='postgres'),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='5432'),
        }
    }
else:
    # SQLite — no setup required, great for feature development and CI
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db_dev.sqlite3',
        }
    }

# ── Cache (override Redis from base.py — no Redis needed in dev) ──────────────
# OTP rate limiting and throttling still work; state is per-process only.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'tawatur-dev',
    }
}

# ── CORS (allow all in dev for easy Postman/simulator testing) ────────────────
CORS_ALLOW_ALL_ORIGINS = True

# ── Email (console backend — no real emails in dev) ───────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ── OTP: return plain OTP in API response during development ──────────────────
# This flag is checked in RequestOTPView to expose the OTP for easy testing.
# It is NEVER set to True in production.
OTP_EXPOSE_IN_RESPONSE = True

# ── Throttle rates: much higher in dev so testing doesn't get blocked ─────────
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['otp']  = '1000/hour'
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['anon']  = '10000/hour'
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['user']  = '10000/hour'
