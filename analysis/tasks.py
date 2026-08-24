from celery import shared_task
from django.db import transaction
from django.utils import timezone

from recruitment.services.common import notify

from accounts.models import User

from .models import AnalysisItem, AnalysisJob, PositionRuleInitialization
from .services.analyze import analyze_item
from .services.rules import RuleGenerationCancelled, create_initial_published_rule


def refresh_job_progress(job):
    job.success_count = job.items.filter(status=AnalysisItem.Status.SUCCESS).count()
    job.failure_count = job.items.filter(
        status__in=[
            AnalysisItem.Status.PARSE_FAILED,
            AnalysisItem.Status.MODEL_ERROR,
        ]
    ).count()
    job.save(update_fields=["success_count", "failure_count"])


def safe_analysis_error(exc):
    if isinstance(exc, TypeError):
        return "系统处理模型结果时发生异常，请联系管理员并重新分析。"
    message = str(exc).strip()
    return message[:500] or "分析执行失败，请稍后重新分析。"


@shared_task
def execute_position_rule_initialization(initialization_id):
    with transaction.atomic():
        initialization = (
            PositionRuleInitialization.objects.select_for_update()
            .select_related("position", "requested_by")
            .get(pk=initialization_id)
        )
        if initialization.status in {
            PositionRuleInitialization.Status.SUCCESS,
            PositionRuleInitialization.Status.CANCELLED,
        }:
            return initialization.status
        if (
            initialization.status
            == PositionRuleInitialization.Status.CANCELLATION_REQUESTED
        ):
            initialization.status = PositionRuleInitialization.Status.CANCELLED
            initialization.finished_at = timezone.now()
            initialization.save(update_fields=["status", "finished_at"])
            return initialization.status
        if initialization.status == PositionRuleInitialization.Status.RUNNING:
            return initialization.status
        initialization.status = PositionRuleInitialization.Status.RUNNING
        initialization.retry_count += 1
        initialization.error_message = ""
        initialization.started_at = timezone.now()
        initialization.finished_at = None
        initialization.save(
            update_fields=[
                "status",
                "retry_count",
                "error_message",
                "started_at",
                "finished_at",
            ]
        )

    actor = (
        initialization.requested_by
        or User.objects.filter(is_active=True, role=User.Role.ADMIN).first()
        or User.objects.filter(is_active=True).first()
    )
    try:
        if not actor:
            raise ValueError("系统中没有可用于记录自动配置的有效用户。")
        rule, _ = create_initial_published_rule(
            initialization.position,
            actor,
            should_cancel=lambda: PositionRuleInitialization.objects.filter(
                pk=initialization.pk,
                status__in=[
                    PositionRuleInitialization.Status.CANCELLATION_REQUESTED,
                    PositionRuleInitialization.Status.CANCELLED,
                ],
            ).exists(),
        )
        initialization.rule_version = rule
        initialization.status = PositionRuleInitialization.Status.SUCCESS
        initialization.finished_at = timezone.now()
        initialization.save(
            update_fields=["rule_version", "status", "finished_at"]
        )
    except RuleGenerationCancelled:
        initialization.status = PositionRuleInitialization.Status.CANCELLED
        initialization.error_message = ""
        initialization.finished_at = timezone.now()
        initialization.save(
            update_fields=["status", "error_message", "finished_at"]
        )
    except Exception as exc:
        initialization.status = PositionRuleInitialization.Status.FAILED
        initialization.error_message = safe_analysis_error(exc)
        initialization.finished_at = timezone.now()
        initialization.save(
            update_fields=["status", "error_message", "finished_at"]
        )
        if actor:
            notify(
                actor,
                "岗位初始规则生成失败",
                f"{initialization.position}：{initialization.error_message}",
                notification_type="error",
                target_url=(
                    f"/recruitment/sync/{initialization.sync_job_id}/"
                    "position-initializations/"
                ),
            )
    return initialization.status


@shared_task
def execute_analysis_job(job_id):
    job = AnalysisJob.objects.get(pk=job_id)
    if job.status in {
        AnalysisJob.Status.CANCELLATION_REQUESTED,
        AnalysisJob.Status.CANCELLED,
    }:
        job.items.filter(status=AnalysisItem.Status.QUEUED).update(
            status=AnalysisItem.Status.CANCELLED,
            finished_at=timezone.now(),
        )
        job.status = AnalysisJob.Status.CANCELLED
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "finished_at"])
        return job.status
    job.status = AnalysisJob.Status.RUNNING
    job.save(update_fields=["status"])
    for item in job.items.filter(status=AnalysisItem.Status.QUEUED):
        if AnalysisJob.objects.filter(
            pk=job.pk,
            status__in=[
                AnalysisJob.Status.CANCELLATION_REQUESTED,
                AnalysisJob.Status.CANCELLED,
            ],
        ).exists():
            break
        try:
            analyze_item(item)
        except Exception as exc:
            item.status = AnalysisItem.Status.MODEL_ERROR
            item.retry_count += 1
            item.error_message = safe_analysis_error(exc)
            item.finished_at = timezone.now()
            item.save(
                update_fields=[
                    "status",
                    "retry_count",
                    "error_message",
                    "finished_at",
                ]
            )
            notify(
                job.requested_by,
                "AI 分析失败",
                f"{item.application.candidate}：{item.error_message}",
                notification_type="error",
                target_url=f"/analysis/jobs/{job.pk}/",
            )
        refresh_job_progress(job)
    with transaction.atomic():
        job = AnalysisJob.objects.select_for_update().get(pk=job.pk)
        refresh_job_progress(job)
        if job.status in {
            AnalysisJob.Status.CANCELLATION_REQUESTED,
            AnalysisJob.Status.CANCELLED,
        }:
            job.items.filter(status=AnalysisItem.Status.QUEUED).update(
                status=AnalysisItem.Status.CANCELLED,
                finished_at=timezone.now(),
            )
            job.status = AnalysisJob.Status.CANCELLED
        elif job.success_count == job.total_count:
            job.status = AnalysisJob.Status.SUCCESS
        elif job.success_count:
            job.status = AnalysisJob.Status.PARTIAL
        else:
            job.status = AnalysisJob.Status.FAILED
        job.finished_at = timezone.now()
        job.save(
            update_fields=[
                "success_count",
                "failure_count",
                "status",
                "finished_at",
            ]
        )
    return job.status
