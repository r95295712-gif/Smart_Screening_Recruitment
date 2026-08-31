from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from recruitment.models import Position, PositionConfiguration
from recruitment.services.common import record_audit

from .forms import PositionRuleForm
from .models import PositionRuleVersion, RuleGenerationOperation
from .services.rules import (
    RuleDraftError,
    RuleGenerationCancelled,
    create_generated_rule,
    delete_rule_version,
    jd_diff,
)


@login_required
def rule_list(request):
    rows = []
    for position in Position.objects.prefetch_related("rule_versions"):
        versions = list(position.rule_versions.all())
        rows.append(
            {
                "position": position,
                "published_rule": next(
                    (
                        rule
                        for rule in versions
                        if rule.status == PositionRuleVersion.Status.PUBLISHED
                    ),
                    None,
                ),
            }
        )
    return render(request, "analysis/rule_list.html", {"rows": rows})


@login_required
def rule_detail(request, rule_id):
    rule = get_object_or_404(
        PositionRuleVersion.objects.select_related(
            "position",
            "created_by",
            "published_by",
        ),
        pk=rule_id,
    )
    return render(request, "analysis/rule_detail.html", {"rule": rule})


@login_required
def rule_edit(request, position_id, rule_id=None):
    position = get_object_or_404(Position, pk=position_id)
    try:
        position.configuration
    except PositionConfiguration.DoesNotExist:
        decision = None
    else:
        decision = position.jd_decisions.filter(is_current=True).first()
        if not decision:
            messages.error(request, "请先确认岗位说明，再配置评估依据与规则。")
            return redirect("recruitment:configuration_detail", pk=position.pk)
    if rule_id:
        rule = get_object_or_404(
            PositionRuleVersion,
            pk=rule_id,
            position=position,
            status=PositionRuleVersion.Status.DRAFT,
        )
    else:
        latest = position.rule_versions.aggregate(value=Max("version"))["value"] or 0
        evaluation_jd = (
            decision.confirmed_jd
            if decision
            else position.evaluation_jd or position.source_jd
        )
        rule = PositionRuleVersion(
            position=position,
            version=latest + 1,
            jd_decision=decision,
            evaluation_jd=evaluation_jd,
            source_jd_snapshot=evaluation_jd,
            rating_thresholds={"priority": 80, "review": 60},
            created_by=request.user,
        )
    form = PositionRuleForm(request.POST or None, instance=rule)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.position = position
        saved.created_by = saved.created_by or request.user
        saved.save()
        record_audit(request.user, "position_rule.save", saved)
        messages.success(request, "岗位规则草稿已保存。")
        return redirect("analysis:rule_edit_version", position_id=position.pk, rule_id=saved.pk)
    return render(
        request,
        "analysis/rule_edit.html",
        {
            "position": position,
            "rule": rule if rule.pk else None,
            "form": form,
            "jd_diff": jd_diff(position.evaluation_jd, position.source_jd),
        },
    )


@login_required
def rule_publish(request, rule_id):
    rule = get_object_or_404(PositionRuleVersion, pk=rule_id)
    if request.method == "POST":
        try:
            rule.publish(request.user)
            record_audit(request.user, "position_rule.publish", rule)
            messages.success(request, f"岗位规则 V{rule.version} 已发布生效。")
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("recruitment:configuration_detail", pk=rule.position_id)


@login_required
def rule_delete(request, rule_id):
    rule = get_object_or_404(PositionRuleVersion, pk=rule_id)
    pos_pk = rule.position_id
    if request.method == "POST":
        force = request.POST.get("force") == "true"
        try:
            delete_rule_version(rule, request.user, force=force)
            messages.success(request, f"岗位规则 V{rule.version} 已成功删除。")
        except ValueError as exc:
            err_msg = str(exc)
            if err_msg.startswith("REQUIRED_FORCE_CONFIRM:"):
                clean_msg = err_msg.replace("REQUIRED_FORCE_CONFIRM:", "")
                messages.warning(request, clean_msg)
            else:
                messages.error(request, err_msg)
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("recruitment:configuration_detail", pk=pos_pk)


@login_required
def rule_generate(request, position_id):
    position = get_object_or_404(Position, pk=position_id)
    if request.method == "POST":
        operation = None
        operation_id = request.POST.get("operation_id", "").strip()
        if operation_id:
            try:
                operation_uuid = UUID(operation_id)
            except ValueError:
                messages.error(request, "本次生成请求无法识别，请重新操作。")
                return redirect("analysis:rule_list")
            operation, created = RuleGenerationOperation.objects.get_or_create(
                pk=operation_uuid,
                defaults={
                    "position": position,
                    "requested_by": request.user,
                },
            )
            if (
                operation.position_id != position.pk
                or operation.requested_by_id != request.user.pk
            ):
                messages.error(request, "本次生成请求无法识别，请重新操作。")
                return redirect("analysis:rule_list")
            if not created and operation.status in {
                RuleGenerationOperation.Status.COMPLETED,
                RuleGenerationOperation.Status.FAILED,
            }:
                messages.warning(request, "该次生成请求已经结束，请勿重复提交。")
                return redirect("analysis:rule_list")

        def cancellation_requested():
            return bool(
                operation
                and RuleGenerationOperation.objects.filter(
                    pk=operation.pk,
                    status__in={
                        RuleGenerationOperation.Status.CANCELLATION_REQUESTED,
                        RuleGenerationOperation.Status.CANCELLED,
                    },
                ).exists()
            )

        try:
            rule = create_generated_rule(
                position,
                request.user,
                should_cancel=cancellation_requested,
            )
            if cancellation_requested():
                rule.delete()
                raise RuleGenerationCancelled("岗位规则草稿生成已取消。")
            if operation:
                operation.status = RuleGenerationOperation.Status.COMPLETED
                operation.finished_at = timezone.now()
                operation.save(update_fields=["status", "finished_at"])
            record_audit(request.user, "position_rule.generate", rule)
            messages.success(request, "AI 岗位规则草稿已生成，请人工核对后发布。")
            return redirect(
                "analysis:rule_edit_version",
                position_id=position.pk,
                rule_id=rule.pk,
            )
        except RuleGenerationCancelled as exc:
            if operation:
                operation.status = RuleGenerationOperation.Status.CANCELLED
                operation.finished_at = timezone.now()
                operation.save(update_fields=["status", "finished_at"])
            messages.warning(request, str(exc))
        except (RuleDraftError, RuntimeError, ValueError) as exc:
            if operation:
                operation.status = RuleGenerationOperation.Status.FAILED
                operation.finished_at = timezone.now()
                operation.save(update_fields=["status", "finished_at"])
            messages.error(request, str(exc))
    return redirect("analysis:rule_list")


@login_required
def rule_generation_cancel(request, position_id):
    position = get_object_or_404(Position, pk=position_id)
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    operation_id = request.POST.get("operation_id", "").strip()
    try:
        operation_uuid = UUID(operation_id)
    except ValueError:
        return JsonResponse({"ok": False}, status=400)
    operation, _ = RuleGenerationOperation.objects.get_or_create(
        pk=operation_uuid,
        defaults={
            "position": position,
            "requested_by": request.user,
            "status": RuleGenerationOperation.Status.CANCELLATION_REQUESTED,
        },
    )
    if (
        operation.position_id != position.pk
        or operation.requested_by_id != request.user.pk
    ):
        return JsonResponse({"ok": False}, status=404)
    if operation.status == RuleGenerationOperation.Status.RUNNING:
        operation.status = RuleGenerationOperation.Status.CANCELLATION_REQUESTED
        operation.save(update_fields=["status"])
    return JsonResponse({"ok": True})
