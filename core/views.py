from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone


def health(request):
    return JsonResponse({"status": "ok", "time": timezone.now().isoformat()})


@login_required
def dashboard(request):
    from analysis.models import AnalysisItem
    from recruitment.models import Application, Notification, Position
    from recruitment.services.configuration import configuration_state
    from reviews.models import ReviewBatch
    from talent_pool.models import TalentMembership

    configuration_counts = {"pending": 0, "update_required": 0}
    for position in Position.objects.all():
        state = configuration_state(position, update_ready_at=False)
        if state.code == "update_required":
            configuration_counts["update_required"] += 1
        elif state.code not in {"ready", "historical"}:
            configuration_counts["pending"] += 1
    context = {
        "position_count": Position.objects.filter(status=Position.Status.ACTIVE).count(),
        "application_count": Application.objects.visible().count(),
        "pending_analysis_count": AnalysisItem.objects.filter(
            status__in=[AnalysisItem.Status.QUEUED, AnalysisItem.Status.RUNNING]
        ).count(),
        "pending_review_count": ReviewBatch.objects.filter(
            status__in=[ReviewBatch.Status.PENDING, ReviewBatch.Status.PARTIAL]
        ).count(),
        "talent_count": TalentMembership.objects.filter(
            status=TalentMembership.Status.ACTIVE
        ).count(),
        "pending_position_configuration_count": configuration_counts["pending"],
        "update_required_position_count": configuration_counts["update_required"],
        "notifications": Notification.objects.filter(user=request.user, read_at__isnull=True)[:8],
    }
    return render(request, "core/dashboard.html", context)
