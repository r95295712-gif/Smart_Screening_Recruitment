from django.urls import path

from .public_views import public_resume, public_review, public_review_item
from .views import (
    add_approved_batch_to_talent,
    add_approved_to_talent,
    clear_rejected_batch_from_review,
    clear_rejected_item_from_review,
    delete_review,
    reopen_review,
    resend_review,
    review_detail,
    review_list,
    revoke_review,
    start_review,
)

app_name = "reviews"

urlpatterns = [
    path("", review_list, name="list"),
    path("<int:pk>/", review_detail, name="detail"),
    path("<int:pk>/delete/", delete_review, name="delete"),
    path(
        "<int:pk>/talent/",
        add_approved_batch_to_talent,
        name="add_approved_batch_to_talent",
    ),
    path(
        "<int:pk>/items/<int:item_id>/talent/",
        add_approved_to_talent,
        name="add_approved_to_talent",
    ),
    path(
        "<int:pk>/clear-rejected/",
        clear_rejected_batch_from_review,
        name="clear_rejected_batch",
    ),
    path(
        "<int:pk>/items/<int:item_id>/clear-rejected/",
        clear_rejected_item_from_review,
        name="clear_rejected_item",
    ),
    path("positions/<int:position_id>/start/", start_review, name="start"),
    path("<int:pk>/revoke/", revoke_review, name="revoke"),
    path("<int:pk>/resend/", resend_review, name="resend"),
    path("<int:pk>/reopen/", reopen_review, name="reopen"),
    path("public/<uuid:public_id>/<str:token>/", public_review, name="public"),
    path(
        "public/<uuid:public_id>/<str:token>/items/<int:item_id>/",
        public_review_item,
        name="public_item",
    ),
    path(
        "public/<uuid:public_id>/<str:token>/items/<int:item_id>/resume/",
        public_resume,
        name="public_resume",
    ),
]
