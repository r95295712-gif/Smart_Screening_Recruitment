from django.urls import path

from .views import (
    add_from_application,
    add_note,
    assign_tag,
    create_tag,
    delete_note,
    delete_tag,
    edit_note,
    edit_tag,
    interview_delete,
    interview_list,
    interview_update_api,
    membership_detail,
    recommend,
    remove_membership,
    remove_tag,
    restore_membership,
    tag_list,
    talent_list,
)

app_name = "talent_pool"

urlpatterns = [
    path("", talent_list, name="list"),
    path("interviews/", interview_list, name="interview_list"),
    path("interviews/<int:pk>/update/", interview_update_api, name="interview_update"),
    path("interviews/<int:pk>/delete/", interview_delete, name="interview_delete"),
    path("tags/", tag_list, name="tag_list"),
    path("<int:pk>/", membership_detail, name="detail"),
    path(
        "applications/<int:application_id>/add/",
        add_from_application,
        name="add_from_application",
    ),
    path("<int:pk>/recommend/", recommend, name="recommend"),
    path("<int:pk>/remove/", remove_membership, name="remove"),
    path("<int:pk>/restore/", restore_membership, name="restore"),
    path("<int:pk>/tags/add/", assign_tag, name="assign_tag"),
    path("<int:pk>/tags/<int:tag_id>/remove/", remove_tag, name="remove_tag"),
    path("<int:pk>/notes/add/", add_note, name="add_note"),
    path("notes/<int:pk>/delete/", delete_note, name="delete_note"),
    path("notes/<int:pk>/edit/", edit_note, name="edit_note"),
    path("tags/create/", create_tag, name="create_tag"),
    path("tags/<int:pk>/edit/", edit_tag, name="edit_tag"),
    path("tags/<int:pk>/delete/", delete_tag, name="delete_tag"),
]
