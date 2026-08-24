from django.urls import path

from .views import (
    cancel_job,
    job_detail,
    job_excel,
    report_detail,
    report_pdf,
    start_analysis,
    usage_dashboard,
)
from .views_rules import (
    rule_detail,
    rule_edit,
    rule_generate,
    rule_generation_cancel,
    rule_list,
    rule_publish,
)

app_name = "analysis"

urlpatterns = [
    path("positions/<int:position_id>/start/", start_analysis, name="start"),
    path("jobs/<int:pk>/", job_detail, name="job_detail"),
    path("jobs/<int:pk>/cancel/", cancel_job, name="job_cancel"),
    path("jobs/<int:pk>/export.xlsx", job_excel, name="job_excel"),
    path("reports/<int:pk>/", report_detail, name="report_detail"),
    path("reports/<int:pk>/export.pdf", report_pdf, name="report_pdf"),
    path("rules/", rule_list, name="rule_list"),
    path("rules/<int:rule_id>/", rule_detail, name="rule_detail"),
    path("rules/positions/<int:position_id>/", rule_edit, name="rule_edit"),
    path(
        "rules/positions/<int:position_id>/generate/",
        rule_generate,
        name="rule_generate",
    ),
    path(
        "rules/positions/<int:position_id>/generate/cancel/",
        rule_generation_cancel,
        name="rule_generation_cancel",
    ),
    path(
        "rules/positions/<int:position_id>/<int:rule_id>/",
        rule_edit,
        name="rule_edit_version",
    ),
    path("rules/<int:rule_id>/publish/", rule_publish, name="rule_publish"),
    path("usage/", usage_dashboard, name="usage"),
]
