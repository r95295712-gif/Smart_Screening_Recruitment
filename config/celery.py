import os

from celery import Celery

from config.env import load_project_env

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
load_project_env()

app = Celery("smart_screening")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
