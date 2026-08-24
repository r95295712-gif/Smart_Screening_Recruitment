from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm

from .models import User


class LockedAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_locked:
            raise forms.ValidationError("账号已暂时锁定，请稍后重试或联系管理员。")


class RequiredPasswordChangeForm(PasswordChangeForm):
    pass


class ManagedUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "email", "first_name", "role")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.must_change_password = True
        if commit:
            user.save()
        return user
