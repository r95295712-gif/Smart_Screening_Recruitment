import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from recruitment.integrations.italent_fields import is_display_value, module_records, module_value
from recruitment.models import Application, Position
from recruitment.services.common import record_audit

from .models import (
    CandidateNote,
    InterviewResultOption,
    TalentInterview,
    TalentMembership,
)


class TalentPoolError(ValueError):
    pass


DEFAULT_INTERVIEW_RESULTS = [
    {"name": "未面试", "color": "muted", "is_default": True},
    {"name": "录用", "color": "success", "is_default": True},
    {"name": "淘汰", "color": "danger", "is_default": True},
]


def ensure_default_result_options():
    for item in DEFAULT_INTERVIEW_RESULTS:
        InterviewResultOption.objects.get_or_create(
            name=item["name"],
            defaults={"color": item["color"], "is_default": item["is_default"]},
        )


def get_all_result_options():
    ensure_default_result_options()
    return list(InterviewResultOption.objects.all().order_by("id"))


def add_custom_result_option(name):
    clean_name = str(name).strip()
    if not clean_name:
        return None
    option, _ = InterviewResultOption.objects.get_or_create(
        name=clean_name,
        defaults={"color": "warning", "is_default": False},
    )
    return option


def ensure_talent_interview(membership):
    candidate = membership.candidate
    position_name = membership.position.name if membership.position else ""
    channel = ""
    latest_app = (
        candidate.applications.filter(deleted_at__isnull=True)
        .order_by("-applied_at", "-created_at")
        .first()
    )
    if latest_app:
        if not position_name and latest_app.position:
            position_name = latest_app.position.name
        if latest_app.source_channel:
            channel = latest_app.source_channel

    interview, created = TalentInterview.objects.get_or_create(
        candidate=candidate,
        defaults={
            "membership": membership,
            "position_name": position_name,
            "channel": channel,
            "result": "未面试",
        },
    )
    if not created:
        updates = []
        if not interview.membership:
            interview.membership = membership
            updates.append("membership")
        if not interview.position_name and position_name:
            interview.position_name = position_name
            updates.append("position_name")
        if not interview.channel and channel:
            interview.channel = channel
            updates.append("channel")
        if updates:
            interview.save(update_fields=updates)
    return interview


def backfill_talent_interviews():
    ensure_default_result_options()
    for mem in TalentMembership.objects.select_related("candidate", "position"):
        ensure_talent_interview(mem)


def parse_candidate_age(profile):
    if not isinstance(profile, dict):
        return ""
    values_to_check = []
    for key in ("Age", "age", "ApplicantAge", "OgAge", "年龄"):
        val = profile.get(key)
        if is_display_value(val):
            values_to_check.append(str(val).strip())

    field_values = profile.get("fieldValues", [])
    if isinstance(field_values, list):
        for item in field_values:
            if isinstance(item, dict):
                name = str(item.get("name", "")).lower()
                text_or_val = item.get("text") or item.get("value")
                if is_display_value(text_or_val):
                    if name in ("age", "ogage", "applicantage", "年龄"):
                        values_to_check.append(str(text_or_val).strip())
                    elif name in ("birthday", "birthdate", "birth", "出生日期", "出生年月"):
                        values_to_check.append(str(text_or_val).strip())

    for key in ("Birthday", "BirthDate", "BirthDay", "birth_date", "birthDate", "出生日期", "出生年月"):
        val = profile.get(key)
        if is_display_value(val):
            values_to_check.append(str(val).strip())

    current_year = timezone.now().year
    for v in values_to_check:
        m_age = re.match(r"^(\d{1,2})\s*(?:岁|years?)?$", v)
        if m_age:
            age_num = int(m_age.group(1))
            if 16 <= age_num <= 80:
                return f"{age_num} 岁"

        m_year = re.search(r"\b(19\d{2}|20\d{2})\b", v)
        if m_year:
            birth_year = int(m_year.group(1))
            if 1940 <= birth_year <= current_year - 15:
                calc_age = current_year - birth_year
                return f"{calc_age} 岁"

    return ""


def parse_candidate_native_place(profile):
    if not isinstance(profile, dict):
        return ""
    keys = (
        "NativePlace",
        "NativePlaceName",
        "Hometown",
        "HouseholdLocation",
        "OriginLocation",
        "BirthPlace",
        "OgNativePlace",
        "native_place",
        "籍贯",
        "户籍所在地",
        "出生地",
    )
    for key in keys:
        val = profile.get(key)
        if is_display_value(val):
            return str(val).strip()

    field_values = profile.get("fieldValues", [])
    if isinstance(field_values, list):
        for item in field_values:
            if isinstance(item, dict):
                name = str(item.get("name", "")).lower()
                text_or_val = item.get("text") or item.get("value")
                if is_display_value(text_or_val):
                    if name in (
                        "nativeplace",
                        "nativeplacename",
                        "hometown",
                        "householdlocation",
                        "originlocation",
                        "birthplace",
                        "ognativeplace",
                        "籍贯",
                        "户籍所在地",
                        "出生地",
                    ):
                        return str(text_or_val).strip()
    return ""


def parse_candidate_skills(skills_text):
    if not skills_text:
        return []
    raw_tokens = re.split(r"[,，;；\n\r|/、•·]+", skills_text)
    skills = []
    seen = set()
    for tok in raw_tokens:
        clean = tok.strip()
        if clean and clean not in seen and len(clean) <= 60:
            skills.append(clean)
            seen.add(clean)
    return skills


def extract_talent_profile_details(candidate):
    profile = candidate.profile if isinstance(candidate.profile, dict) else {}
    modules = candidate.resume_modules if isinstance(candidate.resume_modules, dict) else {}

    age = parse_candidate_age(profile)
    native_place = parse_candidate_native_place(profile)

    edu_list = module_records(modules.get("ApplicantEducation", {}))
    school_display = candidate.school or ""
    if edu_list:
        first_edu = edu_list[0]
        rec_school = module_value(
            first_edu,
            "OgSchoolName",
            "OgSchoolNameSearch",
            "SchoolName",
            "StandardSchoolNameV1",
        ) or candidate.school
        level = module_value(first_edu, "EducationLevel", "Degree")
        major = module_value(first_edu, "MajorName")
        if rec_school:
            extra = [x for x in (level, major) if x]
            if extra:
                school_display = f"{rec_school}（{' · '.join(extra)}）"
            else:
                school_display = rec_school

    work_records = []
    work_list = module_records(modules.get("ApplicantWorkExperience", {}))
    for record in work_list:
        company = module_value(record, "CompanyName", "StandardCompanyName", "Company")
        job_title = module_value(record, "JobTitle", "Title", "PositionName")
        department = module_value(record, "Department")
        start_date = module_value(record, "StartDate", "StartTime")
        end_date = module_value(record, "EndDate", "EndTime")
        job_duty = module_value(
            record,
            "JobDuty",
            "JobDescription",
            "WorkDescription",
            "Duty",
            "WorkSummary",
        )
        if company or job_title or job_duty:
            work_records.append(
                {
                    "company": company or "未填写公司",
                    "job_title": job_title or "-",
                    "department": department or "",
                    "start_date": start_date or "",
                    "end_date": end_date or ("至今" if start_date else ""),
                    "job_duty": job_duty or "",
                }
            )

    if not work_records and candidate.current_company:
        work_records.append(
            {
                "company": candidate.current_company,
                "job_title": "在职经历",
                "department": "",
                "start_date": "",
                "end_date": "至今",
                "job_duty": "",
            }
        )

    skills = parse_candidate_skills(candidate.skills_text)

    return {
        "age": age,
        "native_place": native_place,
        "school_display": school_display or "-",
        "work_records": work_records,
        "skills": skills,
    }


@transaction.atomic
def add_candidate(candidate, actor, position=None):
    resume = candidate.resume_versions.first()
    status = (
        TalentMembership.Status.STALE
        if resume and resume.created_at < timezone.now() - timedelta(days=730)
        else TalentMembership.Status.ACTIVE
    )
    if position is None:
        latest_app = (
            candidate.applications.filter(deleted_at__isnull=True)
            .order_by("-applied_at", "-created_at")
            .first()
        )
        if latest_app:
            position = latest_app.position
    membership, created = TalentMembership.objects.get_or_create(
        candidate=candidate,
        defaults={
            "joined_by": actor,
            "resume_version": resume,
            "status": status,
            "position": position,
        },
    )
    if not created and membership.status not in [
        TalentMembership.Status.ACTIVE,
        TalentMembership.Status.STALE,
    ]:
        membership.status = status
        membership.joined_by = actor
        membership.joined_at = timezone.now()
        membership.resume_version = resume
        if position:
            membership.position = position
        membership.removed_by = None
        membership.removed_at = None
        membership.purge_after = None
        membership.save()
    elif not created and position and not membership.position:
        membership.position = position
        membership.save(update_fields=["position"])
    record_audit(actor, "talent.add", membership)
    ensure_talent_interview(membership)
    return membership


@transaction.atomic
def recommend_candidate(membership, position, actor, stale_confirmed=False):
    if membership.status not in [
        TalentMembership.Status.ACTIVE,
        TalentMembership.Status.STALE,
    ]:
        raise TalentPoolError("只有当前人才库成员可以推荐到岗位。")
    if position.status != Position.Status.ACTIVE:
        raise TalentPoolError("只能推荐到有效岗位。")
    resume = membership.candidate.resume_versions.first()
    if not resume:
        raise TalentPoolError("候选人缺少简历，不能推荐。")
    stale = resume.created_at < timezone.now() - timedelta(days=730)
    if stale and not stale_confirmed:
        raise TalentPoolError("该简历超过 24 个月未更新，请确认后再推荐。")
    existing = Application.objects.visible().filter(
        candidate=membership.candidate,
        position=position,
        source_type=Application.SourceType.TALENT,
    ).first()
    if existing:
        return existing, False
    application = Application.objects.create(
        candidate=membership.candidate,
        position=position,
        source_type=Application.SourceType.TALENT,
        source_channel="人才库推荐",
        application_status="待 HR 处理",
        applied_at=timezone.now(),
        current_resume=resume,
    )
    record_audit(actor, "talent.recommend", application)
    return application, True


def purge_removed_memberships(now=None):
    now = now or timezone.now()
    memberships = TalentMembership.objects.filter(
        status=TalentMembership.Status.REMOVED_PENDING,
        purge_after__lte=now,
    )
    count = 0
    for membership in memberships:
        membership.tag_assignments.all().delete()
        CandidateNote.objects.filter(
            candidate=membership.candidate,
            scope=CandidateNote.Scope.TALENT,
        ).delete()
        membership.status = TalentMembership.Status.REMOVED
        membership.save(update_fields=["status"])
        count += 1
    return count
