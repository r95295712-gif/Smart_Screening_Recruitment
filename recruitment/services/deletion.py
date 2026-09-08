from django.db import transaction
from django.utils import timezone

from recruitment.models import Application, ExclusionMarker
from recruitment.services.common import record_audit


@transaction.atomic
def soft_delete_application(application, actor, reason=""):
    reason = reason or "用户直接删除"
    application.soft_delete(actor, reason)
    from reviews.services import withdraw_application_from_open_reviews

    withdraw_application_from_open_reviews(application)
    record_audit(actor, "application.soft_delete", application, {"reason": reason})
    return application


@transaction.atomic
def soft_delete_applications(applications, actor, reason=""):
    deleted = 0
    for application in applications:
        soft_delete_application(application, actor, reason)
        deleted += 1
    return deleted


@transaction.atomic
def restore_application(application, actor):
    application.restore()
    record_audit(actor, "application.restore", application)
    return application


@transaction.atomic
def purge_expired_applications(now=None):
    now = now or timezone.now()
    applications = list(
        Application.objects.filter(deleted_at__isnull=False, purge_after__lte=now)
    )
    purged = 0
    for application in applications:
        candidate = application.candidate
        if application.application_id:
            ExclusionMarker.objects.get_or_create(application_id=application.application_id)
        from analysis.models import AnalysisItem
        from reviews.models import ReviewItem
        from talent_pool.models import TalentMembership

        ReviewItem.objects.filter(application=application).delete()
        AnalysisItem.objects.filter(application=application).delete()
        application.delete()
        has_other_business_data = Application.objects.filter(candidate=candidate).exists()
        has_talent_membership = TalentMembership.objects.filter(
            candidate=candidate,
            status__in=[
                TalentMembership.Status.ACTIVE,
                TalentMembership.Status.STALE,
                TalentMembership.Status.REMOVED_PENDING,
            ],
        ).exists()
        if not has_other_business_data and not has_talent_membership:
            candidate.delete()
        purged += 1
    return purged


@transaction.atomic
def delete_position(position, actor=None):
    from analysis.models import AnalysisItem, AnalysisJob
    from reviews.models import ReviewBatch, ReviewItem
    from recruitment.models import Application
    from talent_pool.models import TalentMembership

    ReviewItem.objects.filter(application__position=position).delete()
    ReviewBatch.objects.filter(position=position).delete()

    AnalysisItem.objects.filter(application__position=position).delete()
    AnalysisJob.objects.filter(position=position).delete()

    # Clear position reference in talent memberships if any were sourced from this position
    TalentMembership.objects.filter(position=position).update(position=None)

    # Delete applications belonging to this position
    Application.objects.filter(position=position).delete()

    if actor:
        record_audit(actor, "position.delete", position, {"position_name": position.name})

    position_name = position.name
    position.delete()
    return position_name
