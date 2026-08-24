import os

from .base import *

DEBUG = True
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.locmem.EmailBackend"
)
MIDDLEWARE.remove("whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES["staticfiles"] = {
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
