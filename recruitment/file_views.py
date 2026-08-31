from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from core.task_dispatch import dispatch_task
from .models import ResumeVersion
from .presentation import (
    resume_display_name,
    resume_position,
    resume_source_suffix,
)
from .services.common import record_audit
from .tasks import refresh_candidate_resume_preview


@login_required
def download_resume(request, pk):
    resume = get_object_or_404(
        ResumeVersion.objects.select_related("candidate"),
        pk=pk,
    )
    if not resume.source_file:
        return render(
            request,
            "recruitment/file_unavailable.html",
            {
                "candidate": resume.candidate,
                "candidate_name": resume.candidate.name or str(resume.candidate),
                "resume": resume,
                "reason": "该候选人尚未上传或同步原始简历文件。",
                "refresh_available": True,
                "download_available": False,
            },
            status=404,
        )
    try:
        opened_file = resume.source_file.open("rb")
        return FileResponse(
            opened_file,
            as_attachment=True,
            filename=resume_display_name(
                resume.candidate,
                resume_position(resume),
                resume_source_suffix(resume),
            ),
        )
    except (FileNotFoundError, OSError, ValueError):
        return render(
            request,
            "recruitment/file_unavailable.html",
            {
                "candidate": resume.candidate,
                "candidate_name": resume.candidate.name or str(resume.candidate),
                "resume": resume,
                "reason": "简历源文件在服务器存储中未找到，可能存储正在同步或文件已被移除。",
                "refresh_available": True,
                "download_available": False,
            },
            status=404,
        )


@login_required
def preview_resume(request, pk):
    resume = get_object_or_404(
        ResumeVersion.objects.select_related("candidate"),
        pk=pk,
    )
    file_field = resume.standard_pdf or resume.source_file
    if not file_field:
        return render(
            request,
            "recruitment/file_unavailable.html",
            {
                "candidate": resume.candidate,
                "candidate_name": resume.candidate.name or str(resume.candidate),
                "resume": resume,
                "reason": "暂无该候选人的简历在线预览文件。",
                "refresh_available": True,
                "download_available": bool(resume.source_file),
            },
            status=404,
        )

    is_pdf = bool(resume.standard_pdf) or resume.mime_type == "application/pdf"
    if not is_pdf and not (resume.original_filename or "").lower().endswith(".pdf"):
        return render(
            request,
            "recruitment/file_unavailable.html",
            {
                "candidate": resume.candidate,
                "candidate_name": resume.candidate.name or str(resume.candidate),
                "resume": resume,
                "reason": "该原始文件格式不支持直接在线预览，请下载后查看。",
                "refresh_available": True,
                "download_available": bool(resume.source_file),
            },
        )

    try:
        opened_file = file_field.open("rb")
        return FileResponse(
            opened_file,
            content_type="application/pdf",
            as_attachment=False,
            filename=resume_display_name(
                resume.candidate,
                resume_position(resume),
            ),
        )
    except (FileNotFoundError, OSError, ValueError):
        return render(
            request,
            "recruitment/file_unavailable.html",
            {
                "candidate": resume.candidate,
                "candidate_name": resume.candidate.name or str(resume.candidate),
                "resume": resume,
                "reason": "简历预览文件在服务器存储中暂未找到或损坏，您可以尝试重新拉取。",
                "refresh_available": True,
                "download_available": bool(resume.source_file),
            },
            status=404,
        )


@login_required
def refresh_resume_preview_action(request, pk):
    resume = get_object_or_404(
        ResumeVersion.objects.select_related("candidate"),
        pk=pk,
    )
    if request.method == "POST":
        dispatch_task(
            refresh_candidate_resume_preview,
            resume.candidate_id,
            request.user.pk,
        )
        record_audit(
            request.user,
            "resume.preview_retry",
            resume.candidate,
            {"resume_id": str(resume.pk)},
        )
        messages.success(
            request,
            f"{resume.candidate} 的简历在线预览重新获取任务已提交，完成后系统将发送通知。",
        )
    return redirect("recruitment:candidate_detail", pk=resume.candidate_id)

