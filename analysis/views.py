from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import system_admin_required
from core.task_dispatch import dispatch_task
from recruitment.models import Position
from recruitment.services.common import record_audit

from .exports import job_excel_response, report_pdf_response
from .forms import ReportNoteForm
from .models import AnalysisItem, AnalysisJob, AnalysisReport, ModelUsage
from .presentation import build_report_presentation
from .services.jobs import AnalysisJobError, create_analysis_job
from .tasks import execute_analysis_job


@login_required
def start_analysis(request, position_id):
    position = get_object_or_404(Position, pk=position_id)
    if request.method != "POST":
        return redirect("recruitment:position_detail", pk=position.pk)
    try:
        job = create_analysis_job(
            position,
            request.POST.getlist("application_ids"),
            request.user,
            request.POST.get("force_reason", "").strip(),
        )
        dispatch_task(execute_analysis_job, job.pk)
        record_audit(request.user, "analysis.start", job)
        messages.success(request, f"已创建 {job.total_count} 份简历的分析任务。")
        return redirect("analysis:job_detail", pk=job.pk)
    except AnalysisJobError as exc:
        messages.error(request, str(exc))
        return redirect("recruitment:position_detail", pk=position.pk)


@login_required
def job_detail(request, pk):
    job = get_object_or_404(
        AnalysisJob.objects.select_related("position", "requested_by").prefetch_related(
            "items__application__candidate", "items__report", "items__reused_report"
        ),
        pk=pk,
    )
    finished_statuses = {
        AnalysisItem.Status.SUCCESS,
        AnalysisItem.Status.PARSE_FAILED,
        AnalysisItem.Status.MODEL_ERROR,
        AnalysisItem.Status.CANCELLED,
    }
    items = list(job.items.all())
    completed_count = sum(item.status in finished_statuses for item in items)
    progress_percent = (
        round(completed_count * 100 / job.total_count) if job.total_count else 0
    )
    is_active = job.status in {
        AnalysisJob.Status.PENDING,
        AnalysisJob.Status.RUNNING,
        AnalysisJob.Status.CANCELLATION_REQUESTED,
    }
    return render(
        request,
        "analysis/job_detail.html",
        {
            "job": job,
            "completed_count": completed_count,
            "progress_percent": progress_percent,
            "is_active": is_active,
        },
    )


@login_required
def cancel_job(request, pk):
    job = get_object_or_404(AnalysisJob, pk=pk)
    if request.method == "POST" and job.status in {
        AnalysisJob.Status.PENDING,
        AnalysisJob.Status.RUNNING,
    }:
        if job.status == AnalysisJob.Status.PENDING:
            job.status = AnalysisJob.Status.CANCELLED
            job.finished_at = timezone.now()
            job.items.filter(status=AnalysisItem.Status.QUEUED).update(
                status=AnalysisItem.Status.CANCELLED,
                finished_at=timezone.now(),
            )
            job.save(update_fields=["status", "finished_at"])
        else:
            job.status = AnalysisJob.Status.CANCELLATION_REQUESTED
            job.save(update_fields=["status"])
        record_audit(request.user, "analysis.cancel", job)
        messages.success(request, "已提交取消请求，当前正在处理的简历完成后停止。")
    return redirect("analysis:job_detail", pk=job.pk)


@login_required
def report_detail(request, pk):
    report = get_object_or_404(
        AnalysisReport.objects.select_related(
            "item__application__candidate",
            "item__application__position",
            "item__resume_version",
            "item__rule_version",
            "prompt_version",
            "model_version",
        ).prefetch_related("notes__author"),
        pk=pk,
    )
    form = ReportNoteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        note = form.save(commit=False)
        note.report = report
        note.author = request.user
        note.save()
        record_audit(request.user, "analysis_report.note", report)
        messages.success(request, "备注已添加。")
        return redirect("analysis:report_detail", pk=report.pk)
    return render(
        request,
        "analysis/report_detail.html",
        {
            "report": report,
            "form": form,
            "presentation": build_report_presentation(report),
        },
    )


@login_required
def report_pdf(request, pk):
    return report_pdf_response(get_object_or_404(AnalysisReport, pk=pk))


@login_required
def job_excel(request, pk):
    return job_excel_response(get_object_or_404(AnalysisJob, pk=pk))


@system_admin_required
def usage_dashboard(request):
    usage = ModelUsage.objects.select_related("model_version", "position", "user")
    totals = usage.aggregate(
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        estimated_cost=Sum("estimated_cost"),
    )
    return render(
        request,
        "analysis/usage.html",
        {"usage": usage[:200], "totals": totals},
    )
