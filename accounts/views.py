import secrets

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from recruitment.services.common import record_audit
from .decorators import system_admin_required
from .forms import LockedAuthenticationForm, ManagedUserCreationForm, RequiredPasswordChangeForm
from .models import User


class AppLoginView(LoginView):
    authentication_form = LockedAuthenticationForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session["auth_session_version"] = self.request.user.session_version
        now = timezone.now().timestamp()
        self.request.session["last_activity_at"] = now
        self.request.session["login_started_at"] = now
        return response


def logout_view(request):
    logout(request)
    return redirect("accounts:login")


@login_required
def change_password(request):
    form = RequiredPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        update_session_auth_hash(request, user)
        request.session["auth_session_version"] = user.session_version
        messages.success(request, "密码已更新。")
        return redirect("dashboard")
    return render(request, "accounts/change_password.html", {"form": form})


@system_admin_required
def user_list(request):
    return render(request, "accounts/user_list.html", {"users": User.objects.order_by("username")})


@system_admin_required
def user_create(request):
    form = ManagedUserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        record_audit(request.user, "account.create", user)
        messages.success(request, f"账号 {user.username} 已创建。")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {"form": form, "title": "创建账号"})


@system_admin_required
def user_toggle_active(request, pk):
    if request.method != "POST":
        return redirect("accounts:user_list")
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "不能停用当前登录账号。")
        return redirect("accounts:user_list")
    user.is_active = not user.is_active
    user.invalidate_sessions()
    user.save(update_fields=["is_active"])
    record_audit(request.user, "account.toggle_active", user)
    messages.success(request, "账号状态已更新。")
    return redirect("accounts:user_list")


@system_admin_required
def user_unlock(request, pk):
    if request.method == "POST":
        user = get_object_or_404(User, pk=pk)
        user.failed_login_attempts = 0
        user.locked_until = None
        user.save(update_fields=["failed_login_attempts", "locked_until"])
        record_audit(request.user, "account.unlock", user)
        messages.success(request, "账号已解锁。")
    return redirect("accounts:user_list")


@system_admin_required
def user_reset_password(request, pk):
    if request.method != "POST":
        return redirect("accounts:user_list")
    user = get_object_or_404(User, pk=pk)
    temporary_password = secrets.token_urlsafe(12)
    user.set_password(temporary_password)
    user.must_change_password = True
    user.invalidate_sessions()
    user.save(update_fields=["password", "must_change_password"])
    record_audit(request.user, "account.reset_password", user)
    return render(
        request,
        "accounts/temporary_password.html",
        {"managed_user": user, "temporary_password": temporary_password},
    )
