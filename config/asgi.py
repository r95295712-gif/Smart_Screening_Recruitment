import os

from django.core.asgi import get_asgi_application

from config.env import load_project_env

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
load_project_env()

application = get_asgi_application()
