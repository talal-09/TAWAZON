"""Settings for an HTTPS deployment. Set DJANGO_SETTINGS_MODULE to this module."""

import os

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F401,F403


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"{name} is required for production.")
    return value


DEBUG = False
SECRET_KEY = required("DJANGO_SECRET_KEY")
STATIC_ROOT = BASE_DIR / "staticfiles"
ALLOWED_HOSTS = [host.strip() for host in required("DJANGO_ALLOWED_HOSTS").split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in required("DJANGO_CSRF_TRUSTED_ORIGINS").split(",")
    if origin.strip().startswith("https://")
]
if not CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured("DJANGO_CSRF_TRUSTED_ORIGINS must contain an HTTPS origin.")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
# Only set this behind a trusted reverse proxy which overwrites X-Forwarded-Proto.
if os.environ.get("DJANGO_TRUST_PROXY_HTTPS") == "1":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
