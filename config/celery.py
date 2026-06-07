"""
Celery application configuration for Tawatur.
Handles async tasks: PDF certificate generation, OTP expiry cleanup, fraud detection scans.
"""

import os
from celery import Celery

# Point Celery at the development settings by default
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('tawatur')

# Read Celery config from Django settings (all keys prefixed with CELERY_)
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks.py files in every installed Django app
app.autodiscover_tasks()
