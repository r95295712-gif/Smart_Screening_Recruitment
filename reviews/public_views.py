from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from analysis.presentation import build_report_presentation
from recruitment.models import ResumeVersion
from recruitment.services.common import notify

from .models import ReviewBatch, ReviewItem
from .services import refresh_batch_state, verify_batch_token


def get_public_batch(public_id, token):
    batch = get_object_or_404(
        ReviewBatch.objects.select_related("reviewer", "position", "created_by").prefetch_related(
            "items__application__candidate",
            "items__resume_version",
            "items__analysis_report",
        ),
        public_id=public_id,
    )
    if not verify_batch_token(batch, token):
        raise Http404()
    refresh_batch_state(batch)
    return batch


def public_review(request, public_id, token):
    batch = get_public_batch(public_id, token)
    unavailable = batch.status in [
        ReviewBatch.Status.COMPLETED,
        ReviewBatch.Status.REVOKED,
        ReviewBatch.Status.EXPIRED,
    ]
    errors = []
    success_message = (
        "审核结果已保存。"
        if request.GET.get("saved") == "1"
        else ""
    )
    if request.method == "POST" and not unavailable:
        action = request.POST.get("action", "draft")
        active_item_queryset = batch.items.exclude(
            decision=ReviewItem.Decision.WITHDRAWN
        )
        active_items = list(
            active_item_queryset.select_related("application__candidate")
        )
        if action == "clear":
            active_item_queryset.update(
                decision=ReviewItem.Decision.PENDING,
                comment="",
                is_draft=True,
                submitted_at=None,
            )
            refresh_batch_state(batch)
            success_message = "已清空当前填写内容。"
        else:
            for item in active_items:
                decision_key = f"decision_{item.pk}"
                comment_key = f"comment_{item.pk}"
                if decision_key in request.POST or comment_key in request.POST:
                    decision = request.POST.get(
                        decision_key,
                        ReviewItem.Decision.PENDING,
                    )
                    comment = request.POST.get(comment_key, "").strip()
                    if decision not in dict(ReviewItem.Decision.choices):
                        decision = ReviewItem.Decision.PENDING
                    item.decision = decision
                    item.comment = comment
                    item.is_draft = True
                    item.submitted_at = None
                    item.save(
                        update_fields=[
                            "decision",
                            "comment",
                            "is_draft",
                            "submitted_at",
                        ]
                    )
                if (
                    action == "submit"
                    and item.decision
                    == ReviewItem.Decision.DISCUSS
                    and not item.comment
                ):
                    errors.append(
                        f"{item.application.candidate}：该审核结果必须填写备注。"
                    )
                if (
                    action == "submit"
                    and item.decision == ReviewItem.Decision.PENDING
                ):
                    errors.append(f"{item.application.candidate}：请选择审核结果。")
        if action == "submit" and errors:
            success_message = "已保存当前填写内容，请补全后再次提交。"
        elif action == "draft":
            success_message = "草稿已保存。"
        elif action == "submit":
            active_item_queryset.update(
                is_draft=False,
                submitted_at=timezone.now(),
            )
            refresh_batch_state(batch)
            notify(
                batch.created_by,
                "负责人已提交审核结果",
                f"{batch.reviewer} 已完成 {batch.position} 的审核。",
                notification_type="success",
                target_url=f"/reviews/{batch.pk}/",
            )
            unavailable = True
        if not unavailable:
            batch = get_public_batch(public_id, token)
    items = batch.items.exclude(decision=ReviewItem.Decision.WITHDRAWN)
    return render(
        request,
        "reviews/public/review.html",
        {
            "batch": batch,
            "token": token,
            "unavailable": unavailable,
            "errors": errors,
            "success_message": success_message,
            "items": items,
        },
    )


def public_review_item(request, public_id, token, item_id):
    batch = get_public_batch(public_id, token)
    if batch.status in [
        ReviewBatch.Status.COMPLETED,
        ReviewBatch.Status.REVOKED,
        ReviewBatch.Status.EXPIRED,
    ]:
        return redirect("reviews:public", public_id=public_id, token=token)
    item = get_object_or_404(
        batch.items.select_related(
            "application__candidate",
            "resume_version",
            "analysis_report",
        ),
        pk=item_id,
    )
    if item.decision == ReviewItem.Decision.WITHDRAWN:
        raise Http404()
    success_message = ""
    if request.method == "POST":
        decision = request.POST.get(
            "decision",
            ReviewItem.Decision.PENDING,
        )
        if decision not in dict(ReviewItem.Decision.choices):
            decision = ReviewItem.Decision.PENDING
        item.decision = decision
        item.comment = request.POST.get("comment", "").strip()
        item.is_draft = True
        item.submitted_at = None
        item.save(
            update_fields=[
                "decision",
                "comment",
                "is_draft",
                "submitted_at",
            ]
        )
        refresh_batch_state(batch)
        if request.POST.get("return_to") == "list":
            return redirect(
                f"{reverse('reviews:public', args=[batch.public_id, token])}"
                "?saved=1"
            )
        success_message = "审核结果已保存。"
    item.analysis_presentation = (
        build_report_presentation(item.analysis_report)
        if item.analysis_report
        else None
    )
    return render(
        request,
        "reviews/public/review_item.html",
        {
            "batch": batch,
            "item": item,
            "token": token,
            "success_message": success_message,
        },
    )


def public_resume(request, public_id, token, item_id):
    batch = get_public_batch(public_id, token)
    if batch.status in [
        ReviewBatch.Status.COMPLETED,
        ReviewBatch.Status.REVOKED,
        ReviewBatch.Status.EXPIRED,
    ]:
        raise Http404()
    item = get_object_or_404(
        batch.items.select_related("resume_version"),
        pk=item_id,
    )
    if item.decision == ReviewItem.Decision.WITHDRAWN:
        raise Http404()
    resume = item.resume_version
    if not resume:
        raise Http404()
    file_field = resume.standard_pdf
    if not file_field and (
        resume.mime_type == "application/pdf"
        or resume.original_filename.lower().endswith(".pdf")
    ):
        file_field = resume.source_file
    if file_field:
        return FileResponse(
            file_field.open("rb"),
            content_type="application/pdf",
            as_attachment=False,
        )
    return render(
        request,
        "reviews/public/resume_text.html",
        {"candidate_name": item.application.candidate.name, "resume": resume},
    )
