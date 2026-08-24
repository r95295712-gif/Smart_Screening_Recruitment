from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from core.task_dispatch import dispatch_task
from recruitment.models import Position
from recruitment.services.common import record_audit
from talent_pool.models import TalentMembership
from talent_pool.services import add_candidate

from .models import ReviewBatch, ReviewItem, Reviewer
from .services import (
    ReviewError,
    create_review_batch,
    refresh_batch_state,
    revoke_batch,
)
from .tasks import send_review_batch


@login_required
def review_list(request):
    batches = list(ReviewBatch.objects.select_related(
        "reviewer", "position", "created_by"
    ).prefetch_related("items__application__candidate")[:200])
    for batch in batches:
        refresh_batch_state(batch)
    has_pending_email = any(
        batch.email_status == ReviewBatch.EmailStatus.PENDING
        for batch in batches
    )
    return render(
        request,
        "reviews/list.html",
        {
            "batches": batches,
            "has_pending_email": has_pending_email,
        },
    )


@login_required
def review_detail(request, pk):
    batch = get_object_or_404(
        ReviewBatch.objects.select_related(
            "reviewer", "position", "created_by"
        ),
        pk=pk,
    )
    refresh_batch_state(batch)
    items = list(
        batch.items.select_related(
            "application__candidate__talent_membership",
        ).prefetch_related(
            "application__analysis_items__report",
        )
    )
    active_statuses = {
        TalentMembership.Status.ACTIVE,
        TalentMembership.Status.STALE,
    }
    for item in items:
        membership = getattr(item.application.candidate, "talent_membership", None)
        item.active_talent_membership = (
            membership if membership and membership.status in active_statuses else None
        )
        item.can_import_to_talent = (
            item.decision == ReviewItem.Decision.APPROVED
            and not item.is_draft
            and not item.active_talent_membership
        )
    importable_count = sum(item.can_import_to_talent for item in items)
    return render(
        request,
        "reviews/detail.html",
        {
            "batch": batch,
            "items": items,
            "importable_count": importable_count,
        },
    )


@login_required
def add_approved_batch_to_talent(request, pk):
    batch = get_object_or_404(ReviewBatch, pk=pk)
    if request.method == "POST":
        items = batch.items.filter(
            decision=ReviewItem.Decision.APPROVED,
            is_draft=False,
        ).select_related("application__candidate__talent_membership", "application__position")
        imported_count = 0
        existing_count = 0
        for item in items:
            membership = getattr(
                item.application.candidate,
                "talent_membership",
                None,
            )
            if membership and membership.status in {
                TalentMembership.Status.ACTIVE,
                TalentMembership.Status.STALE,
            }:
                existing_count += 1
                continue
            pos = item.application.position if item.application else batch.position
            add_candidate(item.application.candidate, request.user, position=pos)
            imported_count += 1
        if imported_count:
            messages.success(
                request,
                f"已将 {imported_count} 名通过的候选人导入人才库。"
                + (
                    f"另有 {existing_count} 名候选人已在人才库中。"
                    if existing_count
                    else ""
                ),
            )
        elif existing_count:
            messages.info(request, "通过的候选人已全部在人才库中，无需重复导入。")
        else:
            messages.info(request, "当前没有可导入人才库的已提交通过候选人。")
    return redirect("reviews:detail", pk=batch.pk)


@login_required
def add_approved_to_talent(request, pk, item_id):
    batch = get_object_or_404(ReviewBatch, pk=pk)
    item = get_object_or_404(
        ReviewItem.objects.select_related(
            "application__candidate__talent_membership",
            "application__position",
        ),
        pk=item_id,
        batch=batch,
    )
    if request.method == "POST":
        if item.decision != ReviewItem.Decision.APPROVED or item.is_draft:
            messages.error(
                request,
                "只有已提交且审核通过的候选人才能导入人才库。",
            )
        else:
            membership = getattr(
                item.application.candidate,
                "talent_membership",
                None,
            )
            if membership and membership.status in {
                TalentMembership.Status.ACTIVE,
                TalentMembership.Status.STALE,
            }:
                messages.info(request, "该候选人已在人才库中，无需重复导入。")
            else:
                pos = item.application.position if item.application else batch.position
                add_candidate(item.application.candidate, request.user, position=pos)
                messages.success(request, "候选人已导入人才库。")
    return redirect("reviews:detail", pk=batch.pk)


@login_required
def start_review(request, position_id):
    position = get_object_or_404(Position, pk=position_id)
    if request.method != "POST":
        return redirect("recruitment:position_detail", pk=position.pk)
    application_ids = request.POST.getlist("application_ids")
    reviewers = Reviewer.objects.filter(
        is_active=True, position_links__position=position
    ).distinct()
    if not reviewers.exists():
        messages.error(request, "该岗位尚未配置负责人。")
        return redirect("recruitment:position_detail", pk=position.pk)
    selected_ids = list(dict.fromkeys(request.POST.getlist("reviewer_ids")))
    if reviewers.count() > 1 and not selected_ids:
        return render(
            request,
            "reviews/select_reviewer.html",
            {
                "position": position,
                "reviewers": reviewers,
                "application_ids": application_ids,
            },
        )
    if reviewers.count() == 1 and not selected_ids:
        selected_reviewers = [reviewers.first()]
    else:
        selected_reviewers = list(reviewers.filter(pk__in=selected_ids))
        if len(selected_reviewers) != len(selected_ids):
            messages.error(request, "选择的负责人无效，请重新选择。")
            return redirect("recruitment:position_detail", pk=position.pk)
    try:
        expiry_hours = int(request.POST.get("expiry_hours", "72"))
        with transaction.atomic():
            batches = [
                create_review_batch(
                    position,
                    application_ids,
                    reviewer,
                    request.user,
                    expiry_hours,
                )
                for reviewer in selected_reviewers
            ]
        for batch in batches:
            dispatch_task(send_review_batch, batch.pk)
        messages.success(
            request,
            f"已为 {len(batches)} 位负责人创建审核任务并进入邮件发送队列。",
        )
        return redirect("reviews:list")
    except (ReviewError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect("recruitment:position_detail", pk=position.pk)


@login_required
def revoke_review(request, pk):
    batch = get_object_or_404(ReviewBatch, pk=pk)
    if request.method == "POST":
        try:
            revoke_batch(batch, request.user)
            messages.success(request, "审核链接已撤销。")
        except ReviewError as exc:
            messages.error(request, str(exc))
    return redirect("reviews:list")


@login_required
def resend_review(request, pk):
    batch = get_object_or_404(ReviewBatch, pk=pk)
    if request.method == "POST":
        refresh_batch_state(batch)
        if batch.status in [
            ReviewBatch.Status.COMPLETED,
            ReviewBatch.Status.REVOKED,
            ReviewBatch.Status.EXPIRED,
        ]:
            messages.error(request, "已完成或撤销的审核任务不能重发。")
        else:
            batch.status = ReviewBatch.Status.EMAIL_PENDING
            batch.email_status = ReviewBatch.EmailStatus.PENDING
            batch.save(update_fields=["status", "email_status"])
            dispatch_task(send_review_batch, batch.pk)
            messages.success(request, "已重新发送原有效审核链接。")
    return redirect("reviews:list")


@login_required
def reopen_review(request, pk):
    old_batch = get_object_or_404(ReviewBatch, pk=pk)
    if request.method == "POST":
        refresh_batch_state(old_batch)
        if old_batch.status not in [
            ReviewBatch.Status.COMPLETED,
            ReviewBatch.Status.EXPIRED,
        ]:
            messages.error(request, "只有已完成或已过期的审核任务可以重新开启。")
        else:
            application_ids = list(
                old_batch.items.exclude(
                    decision=ReviewItem.Decision.WITHDRAWN
                ).values_list("application_id", flat=True)
            )
            try:
                new_batch = create_review_batch(
                    old_batch.position,
                    application_ids,
                    old_batch.reviewer,
                    request.user,
                    int(request.POST.get("expiry_hours", "72")),
                )
                dispatch_task(send_review_batch, new_batch.pk)
                messages.success(request, "已保留历史结果并生成新的审核链接。")
            except (ReviewError, ValueError) as exc:
                messages.error(request, str(exc))
    return redirect("reviews:list")


@login_required
def delete_review(request, pk):
    batch = get_object_or_404(ReviewBatch, pk=pk)
    if request.method == "POST":
        record_audit(request.user, "review_batch.delete", batch)
        batch.delete()
        messages.success(request, "审核批次记录已删除。")
    return redirect("reviews:list")

