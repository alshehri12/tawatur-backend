"""
Development settings. Extends base.py with local-only overrides.
Never use these settings in production.
"""

import os
import sys
import socket
from .base import *
from decouple import Csv, config

_debug_value = config('DEBUG', default='True').strip().lower()
DEBUG = _debug_value not in {'0', 'false', 'no', 'off', 'prod', 'production', 'release'}

ALLOWED_HOSTS = config(
    'ALLOWED_HOSTS',
    default='localhost,127.0.0.1,0.0.0.0,Abdulrahmans-Mac-Studio.local,.ngrok-free.app,.ngrok-free.dev,.ngrok.io',
    cast=Csv(),
)

# Always append the machine's current LAN IP so the iOS device on the same Wi-Fi
# can reach the server without editing .env every time DHCP reassigns an address.
# Uses a UDP connect trick (no data sent) to find the outbound interface IP.
_lan_ip = None
try:
    _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _s.connect(('8.8.8.8', 80))
    _lan_ip = _s.getsockname()[0]
    _s.close()
    if _lan_ip and not _lan_ip.startswith('127.') and _lan_ip not in ALLOWED_HOSTS:
        ALLOWED_HOSTS = list(ALLOWED_HOSTS) + [_lan_ip]
except Exception:
    pass

# Print current IP on startup so you always know where the app should connect.
if 'runserver' in sys.argv:
    _ip_display = _lan_ip or '?'
    print(f"\n{'='*55}")
    print(f"  تواتر Backend — Development Server")
    print(f"  LAN IP     : http://{_ip_display}:8000/")
    print(f"  Admin      : http://{_ip_display}:8000/admin/")
    print(f"  Discovery  : UDP port 45678 (iOS auto-detects IP)")
    print(f"{'='*55}\n")

    # Start UDP discovery only in the actual server process (not the reloader).
    # Django sets RUN_MAIN=true in the child process that handles requests.
    if os.environ.get('RUN_MAIN') == 'true' and _lan_ip:
        from config.discovery import start_udp_discovery
        start_udp_discovery(_lan_ip)

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
