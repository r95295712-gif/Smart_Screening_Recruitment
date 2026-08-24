import os

from django.core.wsgi import get_wsgi_application

from config.env import load_project_env

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
load_project_env()

application = get_wsgi_application()
