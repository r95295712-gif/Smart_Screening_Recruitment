from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from recruitment.integrations.italent import ITalentClient
from recruitment.models import (
    Application,
    Candidate,
    Notification,
    ResumeVersion,
    SyncJob,
)
from recruitment.services.common import notify, record_audit
from recruitment.services.deletion import purge_expired_applications
from recruitment.services.parsing import parse_resume
from recruitment.services.sync import run_sync_job, safe_sync_error, sync_resume_files
from talent_pool.services import purge_removed_memberships


@shared_task
def execute_sync_job(sync_job_id):
    sync_job = SyncJob.objects.get(pk=sync_job_id)
    run_sync_job(sync_job, ITalentClient())


@shared_task
def parse_resume_task(resume_id):
    return str(parse_resume(ResumeVersion.objects.get(pk=resume_id)).pk)


@shared_task
def pull_application_resume(application_id, requested_by_id):
    from accounts.models import User

    application = Application.objects.select_related("candidate").get(pk=application_id)
    requested_by = User.objects.get(pk=requested_by_id)
    if application.current_resume_id:
        return str(application.current_resume_id)
    try:
        resume, _ = sync_resume_files(application.candidate, ITalentClient())
        if not resume:
            raise ValueError("北森未返回该候选人的原始简历文件。")
        record_audit(
            requested_by,
            "resume.pull_complete",
            application,
            {"resume_id": str(resume.pk)},
        )
        notify(
            requested_by,
            "简历补拉完成",
            f"{application.candidate} 的简历已下载并关联。",
            Notification.Type.SUCCESS,
            f"/recruitment/candidates/{application.candidate_id}/",
        )
        return str(resume.pk)
    except Exception as exc:
        notify(
            requested_by,
            "简历补拉失败",
            safe_sync_error(exc),
            Notification.Type.ERROR,
            f"/recruitment/positions/{application.position_id}/",
        )
        return ""


@shared_task
def refresh_candidate_resume_preview(candidate_id, requested_by_id):
    from accounts.models import User

    candidate = Candidate.objects.get(pk=candidate_id)
    requested_by = User.objects.get(pk=requested_by_id)
    try:
        resume, _ = sync_resume_files(candidate, ITalentClient())
        if not resume:
            raise ValueError("北森暂未返回该候选人的简历文件。")
        if not resume.standard_pdf:
            raise ValueError("北森暂未返回可用的简历在线预览文件。")
        record_audit(
            requested_by,
            "resume.preview_refresh_complete",
            candidate,
            {"resume_id": str(resume.pk)},
        )
        notify(
            requested_by,
            "简历预览更新完成",
            f"{candidate} 的简历在线预览已经更新。",
            Notification.Type.SUCCESS,
            f"/recruitment/candidates/{candidate.pk}/",
        )
        return str(resume.pk)
    except Exception:
        notify(
            requested_by,
            "简历预览更新失败",
            f"{candidate} 的简历在线预览暂未获取成功，请稍后重试。",
            Notification.Type.ERROR,
            f"/recruitment/candidates/{candidate.pk}/",
        )
        return ""


@shared_task
def purge_deleted_applications_task():
    now = timezone.now()
    return {
        "applications": purge_expired_applications(now),
        "talent_memberships": purge_removed_memberships(now),
    }


def create_scheduled_sync(sync_type, start, end):
    job = SyncJob.objects.create(
        sync_type=sync_type,
        window_start=start,
        window_end=end,
    )
    execute_sync_job.delay(job.pk)
    return job.pk


@shared_task
def schedule_incremental_sync():
    end = timezone.now()
    return create_scheduled_sync(
        SyncJob.SyncType.INCREMENTAL,
        end - timedelta(minutes=15),
        end,
    )


@shared_task
def schedule_position_sync():
    end = timezone.now()
    return create_scheduled_sync(
        SyncJob.SyncType.INCREMENTAL,
        end - timedelta(hours=2),
        end,
    )


@shared_task
def schedule_reconciliation_sync():
    end = timezone.now()
    return create_scheduled_sync(
        SyncJob.SyncType.RECONCILIATION,
        end - timedelta(days=7),
        end,
    )
