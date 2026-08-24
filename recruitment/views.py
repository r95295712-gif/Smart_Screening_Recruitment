from datetime import timedelta
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import system_admin_required
from analysis.models import (
    AnalysisItem,
    AnalysisReport,
    PositionRuleInitialization,
)
from analysis.tasks import execute_position_rule_initialization
from core.task_dispatch import dispatch_task
from reviews.models import ReviewBatch, ReviewItem
from talent_pool.models import TalentMembership

from .forms import ApplicationFilterForm, DeleteApplicationForm, PositionFilterForm
from .integrations.italent_fields import module_records, module_value
from .models import Application, Candidate, Notification, Position, SyncJob
from .presentation import build_sync_issue_rows, resume_display_name
from .services.common import record_audit
from .services.configuration import configuration_state
from .services.deletion import (
    restore_application,
    soft_delete_application,
    soft_delete_applications,
)
from .tasks import (
    execute_sync_job,
    pull_application_resume,
    refresh_candidate_resume_preview,
)


@login_required
def position_list(request):
    form = PositionFilterForm(request.GET or None)
    positions = Position.objects.annotate(
        visible_application_count=Count(
            "applications",
            filter=Q(applications__deleted_at__isnull=True)
            & (
                Q(applications__source_type=Application.SourceType.BEISEN)
                | Q(
                    applications__source_type=Application.SourceType.TALENT,
                    applications__linked_recommendations__isnull=True,
                )
            ),
            distinct=True,
        )
    )
    if form.is_valid():
        if form.cleaned_data["q"]:
            positions = positions.filter(
                Q(name__icontains=form.cleaned_data["q"])
                | Q(position_type__icontains=form.cleaned_data["q"])
            )
        if form.cleaned_data["status"]:
            positions = positions.filter(status=form.cleaned_data["status"])
        else:
            positions = positions.filter(status=Position.Status.ACTIVE)
    positions = list(positions)
    for position in positions:
        position.configuration_state_view = configuration_state(
            position,
            update_ready_at=False,
        )
    return render(
        request,
        "recruitment/position_list.html",
        {"positions": positions, "form": form},
    )


@login_required
def position_detail(request, pk):
    position = get_object_or_404(Position, pk=pk)
    form = ApplicationFilterForm(request.GET or None)
    applications = (
        Application.objects.visible()
        .filter(position=position)
        .exclude(
            source_type=Application.SourceType.TALENT,
            linked_recommendations__isnull=False,
        )
        .select_related("candidate", "current_resume")
        .prefetch_related("analysis_items", "review_items")
    )
    if form.is_valid():
        query = form.cleaned_data["q"]
        if query:
            applications = applications.filter(
                Q(candidate__name__icontains=query)
                | Q(candidate__phone=query)
                | Q(candidate__email=query)
                | Q(candidate__current_company__icontains=query)
                | Q(candidate__school__icontains=query)
                | Q(candidate__skills_text__icontains=query)
            )
        analysis_status = form.cleaned_data["analysis_status"]
        if analysis_status == "unanalysed":
            applications = applications.filter(analysis_items__isnull=True)
        elif analysis_status == "success":
            applications = applications.filter(
                analysis_items__status=AnalysisItem.Status.SUCCESS
            )
        elif analysis_status == "pending":
            applications = applications.filter(
                analysis_items__status__in=[
                    AnalysisItem.Status.QUEUED,
                    AnalysisItem.Status.RUNNING,
                ]
            )
        elif analysis_status == "failed":
            applications = applications.filter(
                analysis_items__status__in=[
                    AnalysisItem.Status.PARSE_FAILED,
                    AnalysisItem.Status.MODEL_ERROR,
                ]
            )
        if form.cleaned_data["rating"]:
            applications = applications.filter(
                analysis_items__report__rating=form.cleaned_data["rating"]
            ) | applications.filter(
                analysis_items__reused_report__rating=form.cleaned_data["rating"]
            )
        review_status = form.cleaned_data["review_status"]
        if review_status == "pending":
            applications = applications.filter(
                review_items__batch__status__in=[
                    ReviewBatch.Status.EMAIL_PENDING,
                    ReviewBatch.Status.EMAIL_FAILED,
                    ReviewBatch.Status.PENDING,
                    ReviewBatch.Status.PARTIAL,
                ],
                review_items__decision=ReviewItem.Decision.PENDING,
            )
        elif review_status == "completed":
            applications = applications.filter(review_items__is_draft=False).exclude(
                review_items__decision=ReviewItem.Decision.WITHDRAWN
            )
        elif review_status == "none":
            applications = applications.filter(review_items__isnull=True)
        talent_status = form.cleaned_data["talent_status"]
        if talent_status == "active":
            applications = applications.filter(
                candidate__talent_membership__status=TalentMembership.Status.ACTIVE
            )
        elif talent_status == "none":
            applications = applications.exclude(
                candidate__talent_membership__status=TalentMembership.Status.ACTIVE
            )
        if form.cleaned_data["applied_from"]:
            applications = applications.filter(
                applied_at__date__gte=form.cleaned_data["applied_from"]
            )
        if form.cleaned_data["applied_to"]:
            applications = applications.filter(
                applied_at__date__lte=form.cleaned_data["applied_to"]
            )
    state = configuration_state(position)
    return render(
        request,
        "recruitment/position_detail.html",
        {
            "position": position,
            "applications": applications.distinct(),
            "form": form,
            "configuration_state": state,
        },
    )


@login_required
def candidate_detail(request, pk):
    candidate = get_object_or_404(
        Candidate.objects.prefetch_related(
            "resume_versions",
            Prefetch(
                "applications",
                queryset=Application.objects.visible()
                .select_related("position")
                .prefetch_related("analysis_items"),
                to_attr="visible_applications",
            ),
            "notes",
        ),
        pk=pk,
    )
    membership = TalentMembership.objects.filter(candidate=candidate).first()
    return_position = next(
        (
            application.position
            for application in candidate.visible_applications
            if str(application.position_id) == request.GET.get("position_id", "")
        ),
        None,
    )
    applications_by_resume = {}
    for application in candidate.visible_applications:
        if application.current_resume_id:
            applications_by_resume.setdefault(
                application.current_resume_id,
                application,
            )
    resume_entries = [
        {
            "resume": resume,
            "display_name": resume_display_name(
                candidate,
                applications_by_resume.get(resume.pk).position
                if resume.pk in applications_by_resume
                else None,
            ),
        }
        for resume in candidate.resume_versions.all()
    ]
    education_records = [
        {
            "school": module_value(
                record,
                "OgSchoolName",
                "OgSchoolNameSearch",
                "SchoolName",
                "StandardSchoolNameV1",
            ),
            "college": module_value(record, "CollegeName"),
            "major": module_value(record, "MajorName"),
            "education_level": module_value(record, "EducationLevel"),
            "degree": module_value(record, "Degree"),
            "start_date": module_value(record, "StartDate"),
            "end_date": module_value(record, "EndDate"),
        }
        for record in module_records(
            candidate.resume_modules.get("ApplicantEducation", {})
        )
    ]
    work_records = [
        {
            "company": module_value(
                record, "CompanyName", "StandardCompanyName"
            ),
            "job_title": module_value(record, "JobTitle"),
            "department": module_value(record, "Department"),
            "start_date": module_value(record, "StartDate"),
            "end_date": module_value(record, "EndDate"),
            "job_duty": module_value(record, "JobDuty"),
        }
        for record in module_records(
            candidate.resume_modules.get("ApplicantWorkExperience", {})
        )
    ]
    return render(
        request,
        "recruitment/candidate_detail.html",
        {
            "candidate": candidate,
            "membership": membership,
            "return_position": return_position,
            "resume_entries": resume_entries,
            "education_records": education_records,
            "work_records": work_records,
        },
    )


@login_required
def delete_application(request, pk):
    application = get_object_or_404(Application.objects.visible(), pk=pk)
    form = DeleteApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        soft_delete_application(application, request.user, form.cleaned_data["reason"])
        messages.success(request, "投递记录已移入回收站。")
        return redirect("recruitment:position_detail", pk=application.position_id)
    return render(
        request,
        "recruitment/delete_confirm.html",
        {"application": application, "form": form},
    )


@login_required
def bulk_delete_applications(request, position_id):
    position = get_object_or_404(Position, pk=position_id)
    application_ids = list(dict.fromkeys(request.POST.getlist("application_ids")))
    applications = list(
        Application.objects.visible()
        .filter(pk__in=application_ids, position=position)
        .select_related("candidate")
    )
    if not application_ids:
        messages.error(request, "请至少勾选一条投递记录。")
        return redirect("recruitment:position_detail", pk=position.pk)
    if len(applications) != len(application_ids):
        messages.error(request, "选择中包含无效或不属于当前岗位的投递记录。")
        return redirect("recruitment:position_detail", pk=position.pk)

    form = DeleteApplicationForm(
        request.POST if request.POST.get("confirmed") == "1" else None
    )
    if request.POST.get("confirmed") == "1" and form.is_valid():
        deleted = soft_delete_applications(
            applications,
            request.user,
            form.cleaned_data["reason"],
        )
        messages.success(request, f"已将 {deleted} 条投递记录移入回收站。")
        return redirect("recruitment:position_detail", pk=position.pk)
    return render(
        request,
        "recruitment/bulk_delete_confirm.html",
        {
            "position": position,
            "applications": applications,
            "application_ids": application_ids,
            "form": form,
        },
    )


@login_required
def pull_resume(request, pk):
    application = get_object_or_404(
        Application.objects.visible().select_related("candidate", "position"),
        pk=pk,
        source_type=Application.SourceType.BEISEN,
    )
    if request.method == "POST":
        if application.current_resume_id:
            messages.info(request, "该投递已经有关联简历，无需重复补拉。")
        else:
            dispatch_task(
                pull_application_resume, application.pk, request.user.pk
            )
            record_audit(request.user, "resume.pull_requested", application)
            messages.success(request, "简历补拉任务已提交，结果会通过站内通知告知。")
    return redirect("recruitment:position_detail", pk=application.position_id)


@system_admin_required
def recycle_bin(request):
    applications = Application.objects.filter(deleted_at__isnull=False).select_related(
        "candidate", "position", "deleted_by"
    )
    memberships = TalentMembership.objects.filter(
        status=TalentMembership.Status.REMOVED_PENDING
    ).select_related("candidate", "removed_by")
    return render(
        request,
        "recruitment/recycle_bin.html",
        {"applications": applications, "memberships": memberships},
    )


@system_admin_required
def restore_application_view(request, pk):
    if request.method == "POST":
        application = get_object_or_404(
            Application, pk=pk, deleted_at__isnull=False, purge_after__gt=timezone.now()
        )
        restore_application(application, request.user)
        messages.success(request, "投递记录已恢复。")
    return redirect("recruitment:recycle_bin")


@login_required
def sync_jobs(request):
    sync_options = (
        (SyncJob.SyncType.RECONCILIATION, "最近 7 天（推荐首次测试）"),
        (SyncJob.SyncType.MANUAL, "最近 1 天"),
        (SyncJob.SyncType.FULL, "首次全量（2000 年至今）"),
    )
    if request.method == "POST":
        allowed_types = {value for value, _ in sync_options}
        sync_type = request.POST.get(
            "sync_type", SyncJob.SyncType.RECONCILIATION
        )
        if sync_type not in allowed_types:
            messages.error(request, "请选择有效的同步范围。")
            return redirect("recruitment:sync_jobs")
        now = timezone.now()
        if sync_type == SyncJob.SyncType.FULL:
            window_start = timezone.make_aware(datetime(2000, 1, 1))
        elif sync_type == SyncJob.SyncType.RECONCILIATION:
            window_start = now - timedelta(days=7)
        else:
            window_start = now - timedelta(days=1)
        job = SyncJob.objects.create(
            sync_type=sync_type,
            requested_by=request.user,
            window_start=window_start,
            window_end=now,
        )
        dispatch_task(execute_sync_job, job.pk)
        record_audit(request.user, "sync.start", job)
        messages.success(request, "同步任务已创建。")
        return redirect("recruitment:sync_jobs")
    jobs = list(
        SyncJob.objects.prefetch_related("rule_initializations")[:100]
    )
    has_active_initializations = False
    for job in jobs:
        counts = {
            status: 0
            for status, _ in PositionRuleInitialization.Status.choices
        }
        for initialization in job.rule_initializations.all():
            counts[initialization.status] += 1
        counts["total"] = sum(counts.values())
        job.rule_initialization_summary = counts
        is_job_active = job.status in {
            SyncJob.Status.PENDING,
            SyncJob.Status.RUNNING,
            SyncJob.Status.CANCELLATION_REQUESTED,
        }
        has_active_initializations = has_active_initializations or bool(
            counts[PositionRuleInitialization.Status.RUNNING]
            or counts[PositionRuleInitialization.Status.CANCELLATION_REQUESTED]
            or (is_job_active and counts[PositionRuleInitialization.Status.QUEUED])
        )
    has_active_sync_jobs = (
        SyncJob.objects.filter(
            status__in=[
                SyncJob.Status.PENDING,
                SyncJob.Status.RUNNING,
                SyncJob.Status.CANCELLATION_REQUESTED,
            ]
        )
        .filter(
            Q(requested_by__isnull=False) | Q(sync_type=SyncJob.SyncType.MANUAL)
        )
        .exists()
    )
    return render(
        request,
        "recruitment/sync_jobs.html",
        {
            "jobs": jobs,
            "sync_options": sync_options,
            "has_active_jobs": has_active_sync_jobs or has_active_initializations,
        },
    )


@login_required
def sync_job_issues(request, pk):
    job = get_object_or_404(SyncJob, pk=pk)
    return render(
        request,
        "recruitment/sync_job_issues.html",
        {
            "job": job,
            "issues": build_sync_issue_rows(job),
        },
    )


@login_required
def cancel_sync_job(request, pk):
    job = get_object_or_404(SyncJob, pk=pk)
    if request.method == "POST" and job.status in {
        SyncJob.Status.PENDING,
        SyncJob.Status.RUNNING,
    }:
        if job.status == SyncJob.Status.PENDING:
            job.status = SyncJob.Status.CANCELLED
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "finished_at"])
        else:
            job.status = SyncJob.Status.CANCELLATION_REQUESTED
            job.save(update_fields=["status"])
        record_audit(request.user, "sync.cancel", job)
        messages.success(request, "已提交同步取消请求，已完成的数据将保留。")
    return redirect("recruitment:sync_jobs")


@login_required
def position_initializations(request, pk):
    job = get_object_or_404(SyncJob, pk=pk)
    initializations = job.rule_initializations.select_related(
        "position",
        "requested_by",
        "rule_version",
    )
    has_active_initializations = initializations.filter(
        status__in=[
            PositionRuleInitialization.Status.QUEUED,
            PositionRuleInitialization.Status.RUNNING,
            PositionRuleInitialization.Status.CANCELLATION_REQUESTED,
        ]
    ).exists()
    return render(
        request,
        "recruitment/position_initializations.html",
        {
            "job": job,
            "initializations": initializations,
            "has_active_initializations": has_active_initializations,
        },
    )


@login_required
def retry_position_initialization(request, pk, initialization_id):
    job = get_object_or_404(SyncJob, pk=pk)
    initialization = get_object_or_404(
        PositionRuleInitialization,
        pk=initialization_id,
        sync_job=job,
    )
    if (
        request.method == "POST"
        and initialization.status == PositionRuleInitialization.Status.FAILED
    ):
        initialization.status = PositionRuleInitialization.Status.QUEUED
        initialization.error_message = ""
        initialization.started_at = None
        initialization.finished_at = None
        initialization.save(
            update_fields=[
                "status",
                "error_message",
                "started_at",
                "finished_at",
            ]
        )
        dispatch_task(
            execute_position_rule_initialization,
            initialization.pk,
        )
        record_audit(
            request.user,
            "position_rule_initialization.retry",
            initialization,
            {"position_id": initialization.position_id},
        )
        messages.success(request, "岗位初始规则已重新进入生成队列。")
    return redirect("recruitment:position_initializations", pk=job.pk)


@login_required
def cancel_position_initialization(request, pk, initialization_id):
    job = get_object_or_404(SyncJob, pk=pk)
    initialization = get_object_or_404(
        PositionRuleInitialization,
        pk=initialization_id,
        sync_job=job,
    )
    if request.method == "POST" and initialization.status in {
        PositionRuleInitialization.Status.QUEUED,
        PositionRuleInitialization.Status.RUNNING,
    }:
        if initialization.status == PositionRuleInitialization.Status.QUEUED:
            initialization.status = PositionRuleInitialization.Status.CANCELLED
            initialization.finished_at = timezone.now()
            initialization.save(update_fields=["status", "finished_at"])
        else:
            initialization.status = (
                PositionRuleInitialization.Status.CANCELLATION_REQUESTED
            )
            initialization.save(update_fields=["status"])
        record_audit(
            request.user,
            "position_rule_initialization.cancel",
            initialization,
        )
        messages.success(request, "已提交岗位规则初始化取消请求。")
    return redirect("recruitment:position_initializations", pk=job.pk)


@login_required
def retry_sync_issue(request, pk, candidate_id):
    job = get_object_or_404(SyncJob, pk=pk)
    candidate = get_object_or_404(Candidate, pk=candidate_id)
    retryable_candidate_ids = {
        issue["candidate"].pk
        for issue in build_sync_issue_rows(job)
        if issue["candidate"] and issue["can_retry"]
    }
    if candidate.pk not in retryable_candidate_ids:
        return redirect("recruitment:sync_job_issues", pk=job.pk)
    if request.method == "POST":
        dispatch_task(
            refresh_candidate_resume_preview,
            candidate.pk,
            request.user.pk,
        )
        record_audit(
            request.user,
            "sync.issue_retry",
            job,
            {"candidate_id": candidate.pk},
        )
        messages.success(
            request,
            f"{candidate} 的简历预览重新获取任务已提交，结果会通过站内通知告知。",
        )
    return redirect("recruitment:sync_job_issues", pk=job.pk)


@login_required
def notifications(request):
    queryset = Notification.objects.filter(user=request.user)
    if request.method == "POST":
        queryset.filter(read_at__isnull=True).update(read_at=timezone.now())
        return redirect("recruitment:notifications")
    return render(request, "recruitment/notifications.html", {"notifications": queryset[:100]})


@login_required
def notification_view(request, pk):
    notification = get_object_or_404(
        Notification,
        pk=pk,
        user=request.user,
    )
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    target_url = notification.target_url.strip()
    if (
        target_url.startswith("/")
        and not target_url.startswith("//")
        and "\\" not in target_url
        and "\r" not in target_url
        and "\n" not in target_url
    ):
        return redirect(target_url)
    return redirect("recruitment:notifications")


@login_required
def set_position_status(request, pk):
    position = get_object_or_404(Position, pk=pk)
    if request.method == "POST":
        status = request.POST.get("status")
        if status not in dict(Position.Status.choices):
            messages.error(request, "岗位状态无效。")
        else:
            position.status = status
            position.status_source = Position.StatusSource.MANUAL
            position.manual_status_override = True
            position.save(
                update_fields=[
                    "status",
                    "status_source",
                    "manual_status_override",
                ]
            )
            record_audit(request.user, "position.status_override", position)
            messages.success(request, "岗位状态已人工设置。")
    return redirect("recruitment:position_detail", pk=position.pk)


@login_required
def delete_sync_job(request, pk):
    job = get_object_or_404(SyncJob, pk=pk)
    if request.method == "POST":
        if job.status in {
            SyncJob.Status.PENDING,
            SyncJob.Status.RUNNING,
            SyncJob.Status.CANCELLATION_REQUESTED,
        }:
            messages.error(request, "正在执行中的同步任务无法直接删除，请先取消任务。")
        else:
            job_type_label = job.get_sync_type_display()
            record_audit(request.user, "sync.delete", job)
            job.delete()
            messages.success(request, f"{job_type_label}同步记录已删除。")
    return redirect("recruitment:sync_jobs")


@login_required
def clear_sync_jobs(request):
    if request.method == "POST":
        finished_jobs = SyncJob.objects.filter(
            status__in=[
                SyncJob.Status.SUCCESS,
                SyncJob.Status.PARTIAL,
                SyncJob.Status.FAILED,
                SyncJob.Status.CANCELLED,
            ]
        )
        deleted_count, _ = finished_jobs.delete()
        record_audit(request.user, "sync.clear_all", ("recruitment.SyncJob", ""), metadata={"count": deleted_count})
        messages.success(request, f"已清空 {deleted_count} 条已结束的历史同步任务记录。")
    return redirect("recruitment:sync_jobs")


@login_required
def delete_position_initialization(request, job_pk, pk):
    initialization = get_object_or_404(
        PositionRuleInitialization,
        pk=pk,
        sync_job_id=job_pk,
    )
    if request.method == "POST":
        if initialization.status in {
            PositionRuleInitialization.Status.RUNNING,
            PositionRuleInitialization.Status.CANCELLATION_REQUESTED,
        }:
            messages.error(request, "正在生成中的任务无法直接删除，请先取消任务。")
        else:
            pos_name = str(initialization.position.name)
            record_audit(request.user, "position_rule_initialization.delete", initialization)
            initialization.delete()
            messages.success(request, f"岗位「{pos_name}」的初始化任务记录已删除。")
    return redirect("recruitment:position_initializations", pk=job_pk)


@login_required
def clear_position_initializations(request, job_pk):
    job = get_object_or_404(SyncJob, pk=job_pk)
    if request.method == "POST":
        finished_inits = PositionRuleInitialization.objects.filter(
            sync_job=job,
            status__in=[
                PositionRuleInitialization.Status.SUCCESS,
                PositionRuleInitialization.Status.FAILED,
                PositionRuleInitialization.Status.CANCELLED,
            ],
        )
        deleted_count, _ = finished_inits.delete()
        record_audit(request.user, "position_rule_initialization.clear_all", job, metadata={"count": deleted_count})
        messages.success(request, f"已清理 {deleted_count} 条已结束的规则初始化记录。")
    return redirect("recruitment:position_initializations", pk=job_pk)


@login_required
def delete_notification(request, pk):
    notification = get_object_or_404(
        Notification,
        pk=pk,
        user=request.user,
    )
    if request.method == "POST":
        notification.delete()
        messages.success(request, "通知已删除。")
    return redirect("recruitment:notifications")


@login_required
def clear_notifications(request):
    if request.method == "POST":
        deleted_count, _ = Notification.objects.filter(user=request.user).delete()
        messages.success(request, f"已清空全部 {deleted_count} 条站内通知。")
    return redirect("recruitment:notifications")

