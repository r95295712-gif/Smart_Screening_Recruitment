from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from analysis.services.jd_comparison import create_ai_diff_summary
from recruitment.forms_configuration import (
    JdDecisionForm,
    PositionMatchForm,
    ReferenceDocumentUploadForm,
    ReviewerForm,
)
from recruitment.models import (
    DocumentPosition,
    Position,
    PositionConfiguration,
    ReferenceDocument,
)
from recruitment.services.common import record_audit
from recruitment.services.configuration import (
    confirm_jd,
    configuration_state,
    ensure_position_configuration,
)
from recruitment.services.reference_import import (
    apply_document_reviewers,
    create_reference_document,
    publish_reference_document,
)
from reviews.models import PositionReviewer, Reviewer


def _is_async_request(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _form_error_message(form):
    messages_list = []
    for field_name, errors in form.errors.items():
        label = form.fields[field_name].label if field_name in form.fields else ""
        messages_list.extend(
            f"{label}：{error}" if label else str(error)
            for error in errors
        )
    return "；".join(messages_list)


def _configuration_json(position, message, *, ok=True, status=200):
    state = configuration_state(position)
    configuration = ensure_position_configuration(position)
    document_position = configuration.document_position
    return JsonResponse(
        {
            "ok": ok,
            "message": message,
            "state": {
                "code": state.code,
                "label": state.label,
                "blockers": state.blockers,
                "can_run": state.can_run,
                "can_analyze": state.can_analyze,
                "can_review": state.can_review,
            },
            "reference_position": {
                "id": document_position.pk if document_position else None,
                "title": document_position.title if document_position else "",
                "jd": document_position.jd if document_position else "",
            },
        },
        status=status,
    )


@login_required
def configuration_list(request):
    selected = request.GET.get("status", "pending")
    rows = []
    counts = {
        "pending": 0,
        "update_required": 0,
        "ready": 0,
        "historical": 0,
    }
    for position in Position.objects.all().prefetch_related(
        "rule_versions",
        "reviewer_links__reviewer",
        "jd_decisions",
    ):
        ensure_position_configuration(position)
        state = configuration_state(position)
        group = (
            "historical"
            if state.code == "historical"
            else "ready"
            if state.code == "ready"
            else "update_required"
            if state.code == "update_required"
            else "pending"
        )
        counts[group] += 1
        if selected == group:
            rows.append({"position": position, "state": state})
    return render(
        request,
        "recruitment/configuration/list.html",
        {"rows": rows, "selected": selected, "counts": counts},
    )


@login_required
def configuration_detail(request, pk):
    position = get_object_or_404(Position, pk=pk)
    configuration = ensure_position_configuration(position)
    current_decision = position.jd_decisions.filter(is_current=True).first()
    initial_jd = (
        current_decision.confirmed_jd
        if current_decision
        else position.source_jd
    )
    match_form = PositionMatchForm(
        initial={"document_position": configuration.document_position}
    )
    jd_form = JdDecisionForm(
        initial={
            "decision_type": (
                current_decision.decision_type
                if current_decision
                else "beisen"
            ),
            "confirmed_jd": initial_jd,
        }
    )
    reviewer_form = ReviewerForm()
    ai_result = request.session.get(f"position-ai-diff-{position.pk}", {})
    decision_version_count = position.jd_decisions.count()
    return render(
        request,
        "recruitment/configuration/detail.html",
        {
            "position": position,
            "configuration": configuration,
            "state": configuration_state(position),
            "current_decision": current_decision,
            "match_form": match_form,
            "jd_form": jd_form,
            "reviewer_form": reviewer_form,
            "ai_summary": ai_result.get("summary", "") or (
                current_decision.ai_diff_summary if current_decision else ""
            ),
            "reviewer_links": position.reviewer_links.select_related("reviewer"),
            "rule_versions": position.rule_versions.all(),
            "decision_versions": position.jd_decisions.all(),
            "decision_version_count": decision_version_count,
        },
    )


@login_required
def configuration_confirm_match(request, pk):
    position = get_object_or_404(Position, pk=pk)
    configuration = ensure_position_configuration(position)
    if request.method == "POST":
        form = PositionMatchForm(request.POST)
        if form.is_valid():
            no_match = form.cleaned_data["no_match"]
            configuration.document_position = (
                None if no_match else form.cleaned_data["document_position"]
            )
            configuration.match_status = (
                PositionConfiguration.MatchStatus.NO_MATCH
                if no_match
                else PositionConfiguration.MatchStatus.CONFIRMED
            )
            configuration.match_method = "manual"
            configuration.match_score = 1 if not no_match else 0
            configuration.matched_by = request.user
            configuration.matched_at = timezone.now()
            configuration.save()
            created = apply_document_reviewers(configuration, request.user)
            record_audit(
                request.user,
                "position_match.confirm",
                configuration,
                {"document_position_id": configuration.document_position_id},
            )
            message = "参考岗位匹配已确认。"
            if created:
                message += f" 已自动带出 {created} 名负责人。"
            if _is_async_request(request):
                return _configuration_json(position, message)
            messages.success(request, message)
        else:
            message = _form_error_message(form)
            if _is_async_request(request):
                return _configuration_json(position, message, ok=False, status=400)
            messages.error(request, message)
    return redirect("recruitment:configuration_detail", pk=position.pk)


@login_required
def configuration_confirm_jd(request, pk):
    position = get_object_or_404(Position, pk=pk)
    if request.method == "POST":
        form = JdDecisionForm(request.POST)
        if form.is_valid():
            try:
                ai_result = request.session.pop(
                    f"position-ai-diff-{position.pk}", {}
                )
                decision = confirm_jd(
                    position,
                    form.cleaned_data["decision_type"],
                    request.user,
                    form.cleaned_data["confirmed_jd"],
                    ai_diff_summary=ai_result.get("summary", ""),
                    ai_model_identifier=ai_result.get("model", ""),
                )
                if getattr(decision, "was_unchanged", False):
                    message = (
                        f"岗位说明未发生变化，继续使用 V{decision.version}。"
                    )
                else:
                    message = (
                        f"岗位说明 V{decision.version} 已确认，"
                        "请继续配置评估依据与规则。"
                    )
                if _is_async_request(request):
                    return _configuration_json(position, message)
                messages.success(request, message)
            except ValueError as exc:
                if _is_async_request(request):
                    return _configuration_json(
                        position,
                        str(exc),
                        ok=False,
                        status=400,
                    )
                messages.error(request, str(exc))
        else:
            message = _form_error_message(form)
            if _is_async_request(request):
                return _configuration_json(position, message, ok=False, status=400)
            messages.error(request, message)
    return redirect("recruitment:configuration_detail", pk=position.pk)


@login_required
def configuration_ai_diff(request, pk):
    position = get_object_or_404(Position, pk=pk)
    configuration = ensure_position_configuration(position)
    if request.method == "POST":
        try:
            summary, model_identifier = create_ai_diff_summary(
                position,
                configuration.document_position,
                request.user,
            )
            request.session[f"position-ai-diff-{position.pk}"] = {
                "summary": summary,
                "model": model_identifier,
            }
            record_audit(
                request.user,
                "position_jd.ai_diff",
                position,
                {"document_position_id": configuration.document_position_id},
            )
            messages.success(request, "岗位说明差异摘要已生成，仅供人工确认参考。")
        except Exception:
            messages.error(
                request,
                "差异摘要暂时无法生成，您仍可直接对照两侧岗位说明并继续人工确认。",
            )
    return redirect("recruitment:configuration_detail", pk=position.pk)


@login_required
def configuration_add_reviewer(request, pk):
    position = get_object_or_404(Position, pk=pk)
    if request.method == "POST":
        form = ReviewerForm(request.POST)
        if form.is_valid():
            reviewer, _ = Reviewer.objects.get_or_create(
                name=form.cleaned_data["name"],
                email=form.cleaned_data["email"],
            )
            reviewer.is_active = True
            reviewer.save(update_fields=["is_active"])
            link, created = PositionReviewer.objects.get_or_create(
                position=position,
                reviewer=reviewer,
                defaults={
                    "source_type": PositionReviewer.SourceType.MANUAL,
                    "configured_by": request.user,
                },
            )
            if not created:
                link.source_type = PositionReviewer.SourceType.MANUAL
                link.configured_by = request.user
                link.save(update_fields=["source_type", "configured_by"])
            record_audit(request.user, "position_reviewer.save", link)
            messages.success(request, "审核负责人已保存。")
        else:
            messages.error(request, form.errors.as_text())
    return redirect("recruitment:configuration_detail", pk=position.pk)


@login_required
def configuration_remove_reviewer(request, pk, link_id):
    position = get_object_or_404(Position, pk=pk)
    link = get_object_or_404(PositionReviewer, pk=link_id, position=position)
    if request.method == "POST":
        record_audit(
            request.user,
            "position_reviewer.remove",
            link,
            {"reviewer_id": link.reviewer_id},
        )
        link.delete()
        messages.success(request, "审核负责人已移除。")
    return redirect("recruitment:configuration_detail", pk=position.pk)


@login_required
def reference_documents(request):
    form = ReferenceDocumentUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        reference = create_reference_document(
            form.cleaned_data["file"],
            form.cleaned_data["document_type"],
            request.user,
        )
        if reference.status == ReferenceDocument.Status.PARSE_FAILED:
            messages.error(request, f"资料解析失败：{reference.parse_error}")
        else:
            messages.success(request, "参考资料已解析，请核对后发布。")
        return redirect("recruitment:reference_documents")
    return render(
        request,
        "recruitment/configuration/references.html",
        {
            "form": form,
            "documents": ReferenceDocument.objects.prefetch_related("positions"),
        },
    )


@login_required
def reference_publish(request, pk):
    reference = get_object_or_404(
        ReferenceDocument,
        pk=pk,
        status=ReferenceDocument.Status.DRAFT,
    )
    if request.method == "POST":
        publish_reference_document(reference, request.user)
        messages.success(request, "参考资料已发布为当前有效版本。")
    return redirect("recruitment:reference_documents")
