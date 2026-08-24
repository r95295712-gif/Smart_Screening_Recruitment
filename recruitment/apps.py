from django.apps import AppConfig


class RecruitmentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "recruitment"

    def ready(self):
        from . import signals
