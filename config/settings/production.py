import os

from .base import *
from django.core.exceptions import ImproperlyConfigured

if SECRET_KEY == "development-only-secret-key":
    raise ImproperlyConfigured("生产环境必须配置 DJANGO_SECRET_KEY。")

DEBUG = False

# 针对直接暴露端口（HTTP 访问）或经反向代理（HTTPS 访问）自动适配
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "false").lower() == "true"
SESSION_COOKIE_SECURE = (
    os.getenv("SESSION_COOKIE_SECURE", "true" if SECURE_SSL_REDIRECT else "false").lower()
    == "true"
)
CSRF_COOKIE_SECURE = (
    os.getenv("CSRF_COOKIE_SECURE", "true" if SECURE_SSL_REDIRECT else "false").lower()
    == "true"
)

if SECURE_SSL_REDIRECT:
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# 生产环境默认启用 Celery 异步与 Redis 消息队列
CELERY_TASK_ALWAYS_EAGER = (
    os.getenv("CELERY_TASK_ALWAYS_EAGER", "false").lower() == "true"
)
LOCAL_BACKGROUND_TASKS = (
    os.getenv("LOCAL_BACKGROUND_TASKS", "false").lower() == "true"
)

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)

if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ImproperlyConfigured("EMAIL_USE_TLS 和 EMAIL_USE_SSL 不能同时启用。")

