from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

from .models import LoginFailure


class LockoutModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        username = username or kwargs.get(UserModel.USERNAME_FIELD)
        if not username or password is None:
            return None
        try:
            user = UserModel._default_manager.get_by_natural_key(username)
        except UserModel.DoesNotExist:
            UserModel().set_password(password)
            LoginFailure.objects.create(
                username=username,
                source_ip=self._source_ip(request),
            )
            return None
        if user.is_locked:
            LoginFailure.objects.create(
                username=username,
                user=user,
                source_ip=self._source_ip(request),
            )
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            user.register_successful_login()
            return user
        user.register_failed_login()
        LoginFailure.objects.create(
            username=username,
            user=user,
            source_ip=self._source_ip(request),
        )
        return None

    @staticmethod
    def _source_ip(request):
        if not request:
            return None
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        return (forwarded.split(",")[0].strip() if forwarded else None) or request.META.get(
            "REMOTE_ADDR"
        )
