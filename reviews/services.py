import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from analysis.models import AnalysisItem
from recruitment.models import Application
from recruitment.services.common import record_audit
from recruitment.services.configuration import require_review_configuration

from .models import ReviewBatch, ReviewItem, Reviewer


class ReviewError(ValueError):
    pass


def token_for_batch(batch):
    return hmac.new(
        settings.SECRET_KEY.encode(),
        str(batch.public_id).encode(),
        hashlib.sha256,
    ).hexdigest()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def verify_batch_token(batch, token):
    return hmac.compare_digest(batch.token_hash, token_hash(token))


def refresh_batch_state(batch):
    now = timezone.now()
    if batch.status in [ReviewBatch.Status.REVOKED, ReviewBatch.Status.COMPLETED]:
        return batch
    if batch.expires_at <= now:
        batch.status = ReviewBatch.Status.EXPIRED
        batch.save(update_fields=["status"])
        return batch
    active_items = batch.items.exclude(decision=ReviewItem.Decision.WITHDRAWN)
    if not active_items.exists():
        batch.status = ReviewBatch.Status.REVOKED
        batch.revoked_at = now
    elif active_items.filter(is_draft=False).count() == active_items.count():
        batch.status = ReviewBatch.Status.COMPLETED
        batch.completed_at = now
    elif active_items.filter(is_draft=False).exists():
        batch.status = ReviewBatch.Status.PARTIAL
    elif batch.email_status == ReviewBatch.EmailStatus.SENT:
        batch.status = ReviewBatch.Status.PENDING
    batch.save(update_fields=["status", "revoked_at", "completed_at"])
    return batch


@transaction.atomic
def create_review_batch(position, application_ids, reviewer, user, expiry_hours=72):
    try:
        require_review_configuration(position)
    except ValueError as exc:
        raise ReviewError(str(exc)) from exc
    if expiry_hours not in (24, 72, 168):
        raise ReviewError("审核有效期只能选择 24 小时、72 小时或 7 天。")
    ids = list(dict.fromkeys(application_ids))
    if not ids:
        raise ReviewError("请至少选择一份简历。")
    applications = list(
        Application.objects.visible()
        .filter(pk__in=ids, position=position)
        .select_related("candidate", "current_resume")
    )
    if len(applications) != len(ids):
        raise ReviewError("选择中包含无效或不属于当前岗位的投递。")
    reports_by_application = {}
    for application in applications:
        successful_items = application.analysis_items.filter(
            status=AnalysisItem.Status.SUCCESS
        ).select_related("report", "reused_report").order_by("-created_at")
        if not successful_items.exists():
            raise ReviewError(f"{application.candidate} 尚未完成 AI 分析。")
        current_resume_items = successful_items.filter(
            resume_version=application.current_resume
        )
        report_candidates = list(current_resume_items) or list(successful_items)
        for analysis_item in report_candidates:
            report = (
                getattr(analysis_item, "report", None)
                or analysis_item.reused_report
            )
            if report:
                reports_by_application[application.pk] = report
                break
        if not application.current_resume:
            raise ReviewError(f"{application.candidate} 缺少可审核简历。")
    batch = ReviewBatch(
        reviewer=reviewer,
        position=position,
        created_by=user,
        token_hash="pending",
        expires_at=timezone.now() + timedelta(hours=expiry_hours),
    )
    batch.save()
    batch.token_hash = token_hash(token_for_batch(batch))
    batch.save(update_fields=["token_hash"])
    ReviewItem.objects.bulk_create(
        [
            ReviewItem(
                batch=batch,
                application=application,
                resume_version=application.current_resume,
                analysis_report=reports_by_application.get(application.pk),
            )
            for application in applications
        ]
    )
    record_audit(
        user,
        "review.create",
        batch,
        {"reviewer_id": reviewer.pk, "application_count": len(applications)},
    )
    return batch


@transaction.atomic
def revoke_batch(batch, actor):
    if batch.status in [ReviewBatch.Status.COMPLETED, ReviewBatch.Status.REVOKED]:
        raise ReviewError("该审核任务已结束，不能撤销。")
    batch.status = ReviewBatch.Status.REVOKED
    batch.revoked_at = timezone.now()
    batch.items.filter(is_draft=True).update(decision=ReviewItem.Decision.WITHDRAWN)
    batch.save(update_fields=["status", "revoked_at"])
    record_audit(actor, "review.revoke", batch)
    return batch


@transaction.atomic
def withdraw_application_from_open_reviews(application):
    items = list(
        ReviewItem.objects.select_related("batch").filter(
            application=application,
            is_draft=True,
            batch__status__in=[
                ReviewBatch.Status.EMAIL_PENDING,
                ReviewBatch.Status.EMAIL_FAILED,
                ReviewBatch.Status.PENDING,
                ReviewBatch.Status.PARTIAL,
            ],
        )
    )
    batch_ids = set()
    for item in items:
        item.decision = ReviewItem.Decision.WITHDRAWN
        item.comment = "该简历已由 HR 撤回。"
        item.is_draft = False
        item.submitted_at = timezone.now()
        item.save(
            update_fields=["decision", "comment", "is_draft", "submitted_at"]
        )
        batch_ids.add(item.batch_id)
    for batch in ReviewBatch.objects.filter(pk__in=batch_ids):
        refresh_batch_state(batch)
