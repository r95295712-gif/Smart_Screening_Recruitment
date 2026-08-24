from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from recruitment.models import Application, Position
from recruitment.services.common import record_audit

from .models import CandidateNote, TalentMembership


class TalentPoolError(ValueError):
    pass


@transaction.atomic
def add_candidate(candidate, actor, position=None):
    resume = candidate.resume_versions.first()
    status = (
        TalentMembership.Status.STALE
        if resume and resume.created_at < timezone.now() - timedelta(days=730)
        else TalentMembership.Status.ACTIVE
    )
    if position is None:
        latest_app = (
            candidate.applications.filter(deleted_at__isnull=True)
            .order_by("-applied_at", "-created_at")
            .first()
        )
        if latest_app:
            position = latest_app.position
    membership, created = TalentMembership.objects.get_or_create(
        candidate=candidate,
        defaults={
            "joined_by": actor,
            "resume_version": resume,
            "status": status,
            "position": position,
        },
    )
    if not created and membership.status not in [
        TalentMembership.Status.ACTIVE,
        TalentMembership.Status.STALE,
    ]:
        membership.status = status
        membership.joined_by = actor
        membership.joined_at = timezone.now()
        membership.resume_version = resume
        if position:
            membership.position = position
        membership.removed_by = None
        membership.removed_at = None
        membership.purge_after = None
        membership.save()
    elif not created and position and not membership.position:
        membership.position = position
        membership.save(update_fields=["position"])
    record_audit(actor, "talent.add", membership)
    return membership


@transaction.atomic
def recommend_candidate(membership, position, actor, stale_confirmed=False):
    if membership.status not in [
        TalentMembership.Status.ACTIVE,
        TalentMembership.Status.STALE,
    ]:
        raise TalentPoolError("只有当前人才库成员可以推荐到岗位。")
    if position.status != Position.Status.ACTIVE:
        raise TalentPoolError("只能推荐到有效岗位。")
    resume = membership.candidate.resume_versions.first()
    if not resume:
        raise TalentPoolError("候选人缺少简历，不能推荐。")
    stale = resume.created_at < timezone.now() - timedelta(days=730)
    if stale and not stale_confirmed:
        raise TalentPoolError("该简历超过 24 个月未更新，请确认后再推荐。")
    existing = Application.objects.visible().filter(
        candidate=membership.candidate,
        position=position,
        source_type=Application.SourceType.TALENT,
    ).first()
    if existing:
        return existing, False
    application = Application.objects.create(
        candidate=membership.candidate,
        position=position,
        source_type=Application.SourceType.TALENT,
        source_channel="人才库推荐",
        application_status="待 HR 处理",
        applied_at=timezone.now(),
        current_resume=resume,
    )
    record_audit(actor, "talent.recommend", application)
    return application, True


def purge_removed_memberships(now=None):
    now = now or timezone.now()
    memberships = TalentMembership.objects.filter(
        status=TalentMembership.Status.REMOVED_PENDING,
        purge_after__lte=now,
    )
    count = 0
    for membership in memberships:
        membership.tag_assignments.all().delete()
        CandidateNote.objects.filter(
            candidate=membership.candidate,
            scope=CandidateNote.Scope.TALENT,
        ).delete()
        membership.status = TalentMembership.Status.REMOVED
        membership.save(update_fields=["status"])
        count += 1
    return count
