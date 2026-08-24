from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone


class SessionVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now = timezone.now().timestamp()
            current_version = request.session.get("auth_session_version")
            if current_version != request.user.session_version:
                logout(request)
                return redirect("accounts:login")
            last_activity = request.session.get("last_activity_at", now)
            login_started = request.session.get("login_started_at", now)
            if now - last_activity > 60 * 60 or now - login_started > 12 * 60 * 60:
                logout(request)
                return redirect("accounts:login")
            if now - last_activity >= 60:
                request.session["last_activity_at"] = now
            request.session.setdefault("login_started_at", now)
            if request.user.must_change_password:
                allowed_paths = {
                    reverse("accounts:change_password"),
                    reverse("accounts:logout"),
                }
                if request.path not in allowed_paths and not request.path.startswith("/static/"):
                    return redirect("accounts:change_password")
        return self.get_response(request)
