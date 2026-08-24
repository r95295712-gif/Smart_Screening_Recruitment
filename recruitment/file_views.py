from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from .models import ResumeVersion
from .presentation import (
    resume_display_name,
    resume_position,
    resume_source_suffix,
)


@login_required
def download_resume(request, pk):
    resume = get_object_or_404(
        ResumeVersion.objects.select_related("candidate"),
        pk=pk,
    )
    if not resume.source_file:
        raise Http404("简历文件不存在。")
    return FileResponse(
        resume.source_file.open("rb"),
        as_attachment=True,
        filename=resume_display_name(
            resume.candidate,
            resume_position(resume),
            resume_source_suffix(resume),
        ),
    )


@login_required
def preview_resume(request, pk):
    resume = get_object_or_404(
        ResumeVersion.objects.select_related("candidate"),
        pk=pk,
    )
    file_field = resume.standard_pdf or resume.source_file
    if not file_field:
        raise Http404("简历预览不存在。")
    is_pdf = bool(resume.standard_pdf) or resume.mime_type == "application/pdf"
    if not is_pdf and not (resume.original_filename or "").lower().endswith(".pdf"):
        raise Http404("该原始文件不能直接在线预览，请下载后查看。")
    return FileResponse(
        file_field.open("rb"),
        content_type="application/pdf",
        as_attachment=False,
        filename=resume_display_name(
            resume.candidate,
            resume_position(resume),
        ),
    )
