from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def system_admin_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("accounts:login")
        if not request.user.is_system_admin:
            messages.error(request, "仅管理员可以访问该功能。")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)

    return wrapped
