from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core.views import dashboard, health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("accounts/", include("accounts.urls")),
    path("recruitment/", include("recruitment.urls")),
    path("analysis/", include("analysis.urls")),
    path("reviews/", include("reviews.urls")),
    path("talent/", include("talent_pool.urls")),
    path("", dashboard, name="dashboard"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
