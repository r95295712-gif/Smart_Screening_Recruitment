from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import system_admin_required
from analysis.models import AnalysisItem
from recruitment.models import Application, Candidate, ResumeVersion
from recruitment.services.common import record_audit

from .forms import (
    CandidateNoteForm,
    RecommendationForm,
    TalentFilterForm,
    TalentTagForm,
    TalentTagSearchForm,
)
from .models import CandidateNote, TalentMembership, TalentTag, TalentTagAssignment
from .services import TalentPoolError, add_candidate, recommend_candidate

PAGE_SIZE = 20


@login_required
def talent_list(request):
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
    return render(
        request,
        "talent_pool/detail.html",
        {
            "membership": membership,
            "resume": resume,
            "all_tags": TalentTag.objects.filter(is_active=True),
            "note_form": CandidateNoteForm(),
            "resume_preview_available": resume_preview_available,
            "resume_download_available": bool(resume and resume.source_file),
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
        form = CandidateNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.candidate = membership.candidate
            note.author = request.user
            note.scope = CandidateNote.Scope.TALENT
            note.save()
            messages.success(request, "备注已添加。")
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
