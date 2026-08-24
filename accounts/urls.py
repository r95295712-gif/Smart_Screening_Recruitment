from django.urls import path

from .views import (
    AppLoginView,
    change_password,
    logout_view,
    user_create,
    user_list,
    user_reset_password,
    user_toggle_active,
    user_unlock,
)

app_name = "accounts"

urlpatterns = [
    path("login/", AppLoginView.as_view(), name="login"),
    path("logout/", logout_view, name="logout"),
    path("password/change/", change_password, name="change_password"),
    path("users/", user_list, name="user_list"),
    path("users/create/", user_create, name="user_create"),
    path("users/<int:pk>/toggle/", user_toggle_active, name="user_toggle_active"),
    path("users/<int:pk>/unlock/", user_unlock, name="user_unlock"),
    path("users/<int:pk>/reset-password/", user_reset_password, name="user_reset_password"),
]
