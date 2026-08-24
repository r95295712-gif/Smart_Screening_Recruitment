from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import LoginFailure, User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "智筛招聘",
            {
                "fields": (
                    "role",
                    "must_change_password",
                    "failed_login_attempts",
                    "locked_until",
                    "session_version",
                )
            },
        ),
    )
    list_display = ("username", "email", "role", "is_active", "locked_until")


admin.site.register(LoginFailure)
