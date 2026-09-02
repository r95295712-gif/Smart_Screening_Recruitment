from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.db.models import Count, F, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import system_admin_required
from analysis.models import AnalysisItem, AnalysisReport
from recruitment.models import Application, Candidate, ResumeVersion
from recruitment.services.common import record_audit

from .forms import (
    CandidateNoteForm,
    RecommendationForm,
    TalentFilterForm,
    TalentInterviewFilterForm,
    TalentInterviewForm,
    TalentTagForm,
    TalentTagSearchForm,
)
from .models import (
    CandidateNote,
    InterviewResultOption,
    TalentInterview,
    TalentMembership,
    TalentTag,
    TalentTagAssignment,
)
from .services import (
    TalentPoolError,
    add_candidate,
    add_custom_result_option,
    backfill_talent_interviews,
    extract_talent_profile_details,
    get_all_result_options,
    recommend_candidate,
)

PAGE_SIZE = 20


@login_required
def talent_list(request):
    backfill_talent_interviews()
    form = TalentFilterForm(request.GET or None)

    memberships = TalentMembership.objects.filter(
        status__in=[TalentMembership.Status.ACTIVE, TalentMembership.Status.STALE]
    ).select_related("candidate", "joined_by", "position").prefetch_related("tag_assignments__tag")

    if form.is_valid():
        query = form.cleaned_data["q"]
        if query:
            memberships = memberships.filter(
                Q(candidate__name__icontains=query)
                | Q(candidate__phone=query)
                | Q(candidate__email=query)
                | Q(candidate__skills_text__icontains=query)
                | Q(candidate__current_company__icontains=query)
                | Q(candidate__school__icontains=query)
                | Q(candidate__applications__position__name__icontains=query)
                | Q(position__name__icontains=query)
            )
        if form.cleaned_data.get("position"):
            pos = form.cleaned_data["position"]
            memberships = memberships.filter(
                Q(position=pos) | Q(candidate__applications__position=pos)
            )
        if form.cleaned_data["tag"]:
            memberships = memberships.filter(
                tag_assignments__tag=form.cleaned_data["tag"]
            )

    memberships = memberships.distinct().order_by("-joined_at", "-id")

    paginator = Paginator(memberships, PAGE_SIZE)
    raw_page = request.GET.get("page", 1)
    try:
        page_number = int(raw_page)
        if page_number < 1:
            page_number = 1
        page_obj = paginator.page(page_number)
    except (ValueError, TypeError, PageNotAnInteger):
        page_number = 1
        page_obj = paginator.page(page_number)
    except EmptyPage:
        page_number = paginator.num_pages if paginator.num_pages > 0 else 1
        page_obj = paginator.page(page_number)

    query_params = request.GET.copy()
    if "page" in query_params:
        query_params.pop("page")
    preserved_query = query_params.urlencode()

    if paginator.num_pages > 1:
        try:
            page_range = paginator.get_elided_page_range(
                number=page_obj.number, on_each_side=2, on_ends=1
            )
        except Exception:
            page_range = paginator.page_range
    else:
        page_range = []

    tags = TalentTag.objects.filter(is_active=True).select_related("created_by")
    interview_count = TalentInterview.objects.count()

    candidate_ids = [m.candidate_id for m in page_obj.object_list]
    reports = (
        AnalysisReport.objects.filter(item__application__candidate_id__in=candidate_ids)
        .select_related("item__application__position")
        .order_by("-created_at")
    )
    report_map = {}
    for r in reports:
        cid = r.item.application.candidate_id
        if cid not in report_map:
            report_map[cid] = r
    for m in page_obj.object_list:
        m.latest_report = report_map.get(m.candidate_id)

    return render(
        request,
        "talent_pool/list.html",
        {
            "page_obj": page_obj,
            "memberships": page_obj.object_list,
            "paginator": paginator,
            "page_range": page_range,
            "preserved_query": preserved_query,
            "form": form,
            "tags": tags,
            "tag_form": TalentTagForm(),
            "interview_count": interview_count,
        },
    )


@login_required
def tag_list(request):
    form = TalentTagSearchForm(request.GET or None)
    tags = TalentTag.objects.filter(is_active=True).select_related("created_by").annotate(
        member_count=Count(
            "assignments",
            filter=Q(
                assignments__membership__status__in=[
                    TalentMembership.Status.ACTIVE,
                    TalentMembership.Status.STALE,
                ]
            ),
            distinct=True,
        )
    )
    if form.is_valid():
        q = form.cleaned_data.get("q")
        if q:
            tags = tags.filter(name__icontains=q)
    tags = tags.order_by("name")
    return render(
        request,
        "talent_pool/tag_list.html",
        {
            "tags": tags,
            "form": form,
            "tag_form": TalentTagForm(),
        },
    )


@login_required
def add_from_application(request, application_id):
    application = get_object_or_404(
        Application.objects.visible().select_related("candidate", "position"),
        pk=application_id,
    )
    if not application.analysis_items.filter(status=AnalysisItem.Status.SUCCESS).exists():
        messages.error(request, "只有完成 AI 分析的候选人才能导入人才库。")
        return redirect("recruitment:position_detail", pk=application.position_id)
    if request.method == "POST":
        add_candidate(application.candidate, request.user, position=application.position)
        messages.success(request, "候选人已导入人才库。")
        return redirect("talent_pool:list")
    return render(
        request,
        "talent_pool/add_confirm.html",
        {"application": application},
    )


@login_required
def membership_detail(request, pk):
    membership = get_object_or_404(
        TalentMembership.objects.select_related("candidate", "resume_version", "position").prefetch_related(
            "tag_assignments__tag",
            "candidate__notes__author",
            "candidate__applications__position",
            Prefetch(
                "candidate__resume_versions",
                queryset=ResumeVersion.objects.order_by("-created_at"),
                to_attr="talent_resume_versions",
            ),
        ),
        pk=pk,
    )
    resume = next(
        (
            candidate_resume
            for candidate_resume in membership.candidate.talent_resume_versions
            if candidate_resume.standard_pdf
            or candidate_resume.source_file
            or candidate_resume.extracted_text
        ),
        membership.resume_version,
    )
    resume_preview_available = bool(
        resume
        and (
            resume.standard_pdf
            or (
                resume.source_file
                and (
                    resume.mime_type == "application/pdf"
                    or (resume.original_filename or "").lower().endswith(".pdf")
                )
            )
        )
    )
    notes = list(membership.candidate.notes.all())
    unified_remark = "\n\n".join([n.content.strip() for n in notes if n.content.strip()])
    latest_note = notes[-1] if notes else None
    latest_note_time = latest_note.updated_at if latest_note else None
    latest_note_author = (
        latest_note.author.username if (latest_note and latest_note.author) else ""
    )
    details = extract_talent_profile_details(membership.candidate)
    direct_report_ids = AnalysisReport.objects.filter(
        item__application__candidate=membership.candidate
    ).values_list("id", flat=True)
    reused_report_ids = AnalysisItem.objects.filter(
        application__candidate=membership.candidate,
        reused_report__isnull=False,
    ).values_list("reused_report_id", flat=True)
    all_report_ids = set(direct_report_ids) | set(reused_report_ids)

    analysis_reports = list(
        AnalysisReport.objects.filter(id__in=all_report_ids)
        .select_related("item__application__position", "item__rule_version")
        .order_by("-created_at")
    )
    latest_report = analysis_reports[0] if analysis_reports else None

    return render(
        request,
        "talent_pool/detail.html",
        {
            "membership": membership,
            "resume": resume,
            "all_tags": TalentTag.objects.filter(is_active=True),
            "note_form": CandidateNoteForm(),
            "unified_remark": unified_remark,
            "latest_note_time": latest_note_time,
            "latest_note_author": latest_note_author,
            "resume_preview_available": resume_preview_available,
            "resume_download_available": bool(resume and resume.source_file),
            "analysis_reports": analysis_reports,
            "latest_report": latest_report,
            "age": details["age"],
            "native_place": details["native_place"],
            "school_display": details["school_display"],
            "work_records": details["work_records"],
            "skills": details["skills"],
        },
    )


@login_required
def create_tag(request):
    if request.method == "POST":
        form = TalentTagForm(request.POST)
        if form.is_valid():
            tag = form.save(commit=False)
            tag.created_by = request.user
            tag.save()
            record_audit(request.user, "talent_tag.create", tag)
            messages.success(request, "团队标签已创建。")
        else:
            messages.error(request, "标签名称无效或已存在。")
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(next_url)
    return redirect("talent_pool:tag_list")


@login_required
def edit_tag(request, pk):
    tag = get_object_or_404(TalentTag, pk=pk)
    next_url = request.POST.get("next") or request.GET.get("next")
    if tag.created_by_id != request.user.pk and not request.user.is_system_admin:
        messages.error(request, "只能修改自己创建的标签。")
        return redirect(next_url or "talent_pool:tag_list")
    if request.method == "POST":
        form = TalentTagForm(request.POST, instance=tag)
        if form.is_valid():
            form.save()
            messages.success(request, "标签已更新。")
    if next_url:
        return redirect(next_url)
    return redirect("talent_pool:tag_list")


@login_required
def delete_tag(request, pk):
    tag = get_object_or_404(TalentTag, pk=pk)
    next_url = request.POST.get("next") or request.GET.get("next")
    if tag.created_by_id != request.user.pk and not request.user.is_system_admin:
        messages.error(request, "只能删除自己创建的标签。")
        return redirect(next_url or "talent_pool:tag_list")
    if request.method == "POST":
        tag.is_active = False
        tag.save(update_fields=["is_active"])
        tag.assignments.all().delete()
        messages.success(request, "标签已删除。")
    if next_url:
        return redirect(next_url)
    return redirect("talent_pool:tag_list")


@login_required
def assign_tag(request, pk):
    membership = get_object_or_404(TalentMembership, pk=pk)
    if request.method == "POST":
        tag = get_object_or_404(TalentTag, pk=request.POST.get("tag_id"), is_active=True)
        TalentTagAssignment.objects.get_or_create(
            membership=membership,
            tag=tag,
            defaults={"assigned_by": request.user},
        )
    return redirect("talent_pool:detail", pk=membership.pk)


@login_required
def remove_tag(request, pk, tag_id):
    membership = get_object_or_404(TalentMembership, pk=pk)
    if request.method == "POST":
        TalentTagAssignment.objects.filter(
            membership=membership, tag_id=tag_id
        ).delete()
    return redirect("talent_pool:detail", pk=membership.pk)


@login_required
def add_note(request, pk):
    membership = get_object_or_404(TalentMembership, pk=pk)
    if request.method == "POST":
        content = request.POST.get("content", "").strip()
        existing_notes = list(
            CandidateNote.objects.filter(candidate=membership.candidate).order_by("-updated_at", "-created_at")
        )
        if existing_notes:
            primary_note = existing_notes[0]
            if content:
                primary_note.content = content
                primary_note.author = request.user
                primary_note.scope = CandidateNote.Scope.TALENT
                primary_note.save()
                if len(existing_notes) > 1:
                    CandidateNote.objects.filter(
                        candidate=membership.candidate
                    ).exclude(pk=primary_note.pk).delete()
                messages.success(request, "人才库备注已保存。")
            else:
                CandidateNote.objects.filter(candidate=membership.candidate).delete()
                messages.success(request, "备注已清空。")
        else:
            if content:
                CandidateNote.objects.create(
                    candidate=membership.candidate,
                    author=request.user,
                    scope=CandidateNote.Scope.TALENT,
                    content=content,
                )
                messages.success(request, "人才库备注已保存。")
            else:
                messages.info(request, "备注内容为空，未作修改。")
        record_audit(request.user, "talent_note.save", membership)
    return redirect("talent_pool:detail", pk=membership.pk)


@login_required
def delete_note(request, pk):
    note = get_object_or_404(CandidateNote, pk=pk)
    membership = get_object_or_404(TalentMembership, candidate=note.candidate)
    if note.author_id != request.user.pk and not request.user.is_system_admin:
        messages.error(request, "只能删除自己的备注。")
    elif request.method == "POST":
        note.delete()
        messages.success(request, "备注已删除。")
    return redirect("talent_pool:detail", pk=membership.pk)


@login_required
def edit_note(request, pk):
    note = get_object_or_404(CandidateNote, pk=pk)
    membership = get_object_or_404(TalentMembership, candidate=note.candidate)
    if note.author_id != request.user.pk:
        messages.error(request, "只能修改自己的备注。")
    elif request.method == "POST":
        form = CandidateNoteForm(request.POST, instance=note)
        if form.is_valid():
            form.save()
            messages.success(request, "备注已更新。")
    return redirect("talent_pool:detail", pk=membership.pk)


@login_required
def recommend(request, pk):
    membership = get_object_or_404(
        TalentMembership.objects.select_related("candidate"), pk=pk
    )
    form = RecommendationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            application, created = recommend_candidate(
                membership,
                form.cleaned_data["position"],
                request.user,
                form.cleaned_data["stale_confirmed"],
            )
            messages.success(
                request,
                "已创建人才库推荐记录。" if created else "该岗位已有推荐记录。",
            )
            return redirect(
                "recruitment:position_detail", pk=application.position_id
            )
        except TalentPoolError as exc:
            form.add_error(None, str(exc))
    return render(
        request,
        "talent_pool/recommend.html",
        {"membership": membership, "form": form},
    )


@login_required
def remove_membership(request, pk):
    membership = get_object_or_404(TalentMembership, pk=pk)
    if request.method == "POST":
        membership.remove(request.user)
        record_audit(request.user, "talent.remove", membership)
        messages.success(request, "候选人已移出人才库，管理员可在 3 天内恢复。")
    return redirect("talent_pool:list")


@system_admin_required
def restore_membership(request, pk):
    membership = get_object_or_404(
        TalentMembership, pk=pk, status=TalentMembership.Status.REMOVED_PENDING
    )
    if request.method == "POST":
        membership.restore()
        record_audit(request.user, "talent.restore", membership)
        messages.success(request, "人才库成员已恢复。")
    return redirect("recruitment:recycle_bin")


@login_required
def interview_list(request):
    backfill_talent_interviews()
    form = TalentInterviewFilterForm(request.GET or None)

    interviews = TalentInterview.objects.select_related("candidate", "membership").all()

    if form.is_valid():
        q = form.cleaned_data.get("q")
        if q:
            interviews = interviews.filter(
                Q(candidate__name__icontains=q)
                | Q(position_name__icontains=q)
                | Q(first_interviewer__icontains=q)
                | Q(second_interviewer__icontains=q)
                | Q(notes__icontains=q)
                | Q(channel__icontains=q)
                | Q(result__icontains=q)
            )
        pos = form.cleaned_data.get("position")
        if pos:
            interviews = interviews.filter(position_name__icontains=pos)
        res = form.cleaned_data.get("result")
        if res:
            interviews = interviews.filter(result=res)
        interviewer = form.cleaned_data.get("interviewer")
        if interviewer:
            interviews = interviews.filter(
                Q(first_interviewer__icontains=interviewer)
                | Q(second_interviewer__icontains=interviewer)
            )
        ch = form.cleaned_data.get("channel")
        if ch:
            interviews = interviews.filter(channel__icontains=ch)
        d_from = form.cleaned_data.get("date_from")
        if d_from:
            interviews = interviews.filter(interview_date__gte=d_from)
        d_to = form.cleaned_data.get("date_to")
        if d_to:
            interviews = interviews.filter(interview_date__lte=d_to)

    interviews = interviews.order_by(
        models.F("interview_date").desc(nulls_last=True),
        "-created_at",
        "-id",
    )

    paginator = Paginator(interviews, PAGE_SIZE)
    raw_page = request.GET.get("page", 1)
    try:
        page_number = int(raw_page)
        if page_number < 1:
            page_number = 1
        page_obj = paginator.page(page_number)
    except (ValueError, TypeError, PageNotAnInteger):
        page_number = 1
        page_obj = paginator.page(page_number)
    except EmptyPage:
        page_number = paginator.num_pages if paginator.num_pages > 0 else 1
        page_obj = paginator.page(page_number)

    query_params = request.GET.copy()
    if "page" in query_params:
        query_params.pop("page")
    preserved_query = query_params.urlencode()

    if paginator.num_pages > 1:
        try:
            page_range = paginator.get_elided_page_range(
                number=page_obj.number, on_each_side=2, on_ends=1
            )
        except Exception:
            page_range = paginator.page_range
    else:
        page_range = []

    all_positions = sorted(
        set(
            p.strip()
            for p in TalentInterview.objects.exclude(position_name="").values_list(
                "position_name", flat=True
            )
            if p and p.strip()
        )
    )
    first_ints = [
        x.strip()
        for x in TalentInterview.objects.exclude(first_interviewer="").values_list(
            "first_interviewer", flat=True
        )
        if x and x.strip()
    ]
    second_ints = [
        x.strip()
        for x in TalentInterview.objects.exclude(second_interviewer="").values_list(
            "second_interviewer", flat=True
        )
        if x and x.strip()
    ]
    all_interviewers = sorted(set(first_ints + second_ints))

    result_options = get_all_result_options()

    return render(
        request,
        "talent_pool/interview_list.html",
        {
            "page_obj": page_obj,
            "interviews": page_obj.object_list,
            "paginator": paginator,
            "page_range": page_range,
            "preserved_query": preserved_query,
            "form": form,
            "positions": all_positions,
            "interviewers": all_interviewers,
            "result_options": result_options,
        },
    )


@login_required
def interview_update_api(request, pk):
    interview = get_object_or_404(TalentInterview, pk=pk)
    if request.method == "POST":
        import json
        from datetime import datetime

        if request.content_type == "application/json":
            try:
                data = json.loads(request.body.decode("utf-8"))
            except Exception:
                data = {}
        else:
            data = request.POST

        if "interview_date" in data:
            date_val = str(data.get("interview_date", "")).strip()
            if date_val:
                try:
                    interview.interview_date = datetime.strptime(
                        date_val, "%Y-%m-%d"
                    ).date()
                except ValueError:
                    pass
            else:
                interview.interview_date = None

        if "interview_time" in data:
            interview.interview_time = str(data.get("interview_time", "")).strip()

        if "position_name" in data:
            interview.position_name = str(data.get("position_name", "")).strip()

        if "first_interviewer" in data:
            interview.first_interviewer = str(
                data.get("first_interviewer", "")
            ).strip()

        if "second_interviewer" in data:
            interview.second_interviewer = str(
                data.get("second_interviewer", "")
            ).strip()

        if "result" in data:
            res_val = str(data.get("result", "")).strip()
            if res_val:
                add_custom_result_option(res_val)
                interview.result = res_val

        if "notes" in data:
            interview.notes = str(data.get("notes", "")).strip()

        if "channel" in data:
            interview.channel = str(data.get("channel", "")).strip()

        interview.save()
        record_audit(request.user, "talent_interview.update", interview)

        return JsonResponse(
            {
                "ok": True,
                "message": "面试记录已更新。",
                "interview": {
                    "id": interview.pk,
                    "date_str": (
                        interview.interview_date.strftime("%Y-%m-%d")
                        if interview.interview_date
                        else ""
                    ),
                    "date_formatted": interview.formatted_date_with_weekday or "-",
                    "time": interview.interview_time or "-",
                    "position_name": interview.position_name or "-",
                    "first_interviewer": interview.first_interviewer or "",
                    "second_interviewer": interview.second_interviewer or "",
                    "result": interview.result,
                    "result_color_type": interview.result_color_type,
                    "notes": interview.notes or "",
                    "channel": interview.channel or "",
                },
            }
        )
    return JsonResponse({"ok": False, "message": "Method not allowed"}, status=405)


@login_required
def interview_delete(request, pk):
    interview = get_object_or_404(TalentInterview, pk=pk)
    if request.method == "POST":
        interview.delete()
        record_audit(request.user, "talent_interview.delete", interview)
        messages.success(request, "面试记录已删除。")
    return redirect("talent_pool:interview_list")

