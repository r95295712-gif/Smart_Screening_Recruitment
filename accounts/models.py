from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        HR = "hr", "HR"
        ADMIN = "admin", "管理员"

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.HR)
    must_change_password = models.BooleanField(default=True)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    session_version = models.PositiveIntegerField(default=1)

    @property
    def is_system_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    def register_failed_login(self):
        now = timezone.now()
        self.failed_login_attempts += 1
        fields = ["failed_login_attempts"]
        if self.failed_login_attempts >= 5:
            self.locked_until = now + timedelta(minutes=15)
            fields.append("locked_until")
        self.save(update_fields=fields)

    def register_successful_login(self):
        if self.failed_login_attempts or self.locked_until:
            self.failed_login_attempts = 0
            self.locked_until = None
            self.save(update_fields=["failed_login_attempts", "locked_until"])

    def invalidate_sessions(self):
        self.session_version += 1
        self.save(update_fields=["session_version"])


class LoginFailure(models.Model):
    username = models.CharField(max_length=150, db_index=True)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="login_failures",
    )
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-attempted_at"]
