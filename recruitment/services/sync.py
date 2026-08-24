from collections.abc import Iterable
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from analysis.models import PositionRuleInitialization
from analysis.tasks import execute_position_rule_initialization
from core.task_dispatch import dispatch_task
from recruitment.integrations.italent_fields import (
    field_value,
    list_text,
    module_text,
)
from recruitment.models import (
    Application,
    Candidate,
    ExclusionMarker,
    Position,
    ResumeVersion,
    SyncJob,
)
from recruitment.services.common import notify
from recruitment.services.files import attach_standard_pdf, save_resume_bytes
from recruitment.services.parsing import parse_resume


def extract_items(payload):
    if isinstance(payload, list):
        return payload
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("items", "list", "records", "result"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


def value_from(payload, *names, default=""):
    for name in names:
        if payload.get(name) not in (None, ""):
            return payload[name]
    return default


def chunks(values, size=100):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def candidate_profile_value(profile, *names, prefer_text=True):
    return value_from(
        profile,
        *names,
        default=field_value(
            profile,
            *names,
            prefer_text=prefer_text,
        ),
    )


def skills_from(profile, modules):
    profile_skills = candidate_profile_value(
        profile,
        "skills",
        "skillText",
        "ApplicantSkill",
    )
    if profile_skills:
        return str(profile_skills)
    return module_text(
        (modules or {}).get("Skill", {}),
        ("SkillName", "SkillLevel", "SkillDescription", "UseTime"),
    )


def application_channel(payload, candidate):
    channel = value_from(
        payload,
        "source",
        "channel",
        default=field_value(
            payload,
            "Source",
            "Channel",
            "SubmissionChannel",
            "InitialSubmissionChannel",
            "BelongSubmissionChannel",
            "LastSubmissionChannel",
            "InitialSubmissionMedium",
            prefer_text=True,
        ),
    )
    if not channel:
        return ""
    profile = candidate.profile if isinstance(candidate.profile, dict) else {}
    for name in (
        "InitialSubmissionChannel",
        "BelongSubmissionChannel",
        "LastSubmissionChannel",
    ):
        entry = next(
            (
                item
                for item in profile.get("fieldValues", [])
                if isinstance(item, dict) and item.get("name") == name
            ),
            None,
        )
        if entry and str(entry.get("value")) == str(channel) and entry.get("text"):
            return str(entry["text"])
    return str(channel)


@transaction.atomic
def upsert_candidate(profile, modules=None):
    applicant_id = str(value_from(profile, "applicantId", "ApplicantId", "id"))
    if not applicant_id:
        raise ValueError("候选人数据缺少 applicantId。")
    candidate, _ = Candidate.objects.update_or_create(
        applicant_id=applicant_id,
        defaults={
            "name": candidate_profile_value(
                profile, "name", "Name", "applicantName"
            ),
            "phone": candidate_profile_value(
                profile, "phone", "mobile", "Mobile"
            ),
            "email": candidate_profile_value(
                profile, "email", "Email", "OgEmail"
            ),
            "current_company": candidate_profile_value(
                profile,
                "currentCompany",
                "company",
                "Company",
                "LastCompany",
                "StandardLastCompanyName",
            ),
            "school": candidate_profile_value(
                profile,
                "school",
                "School",
                "OgLastSchool",
                "OgAllSchool",
                "LastSchool",
                "StandardLastSchool",
                "HighestSchool",
            ),
            "skills_text": skills_from(profile, modules),
            "profile": profile,
            "resume_modules": modules or {},
            "last_synced_at": timezone.now(),
        },
    )
    return candidate


@transaction.atomic
def upsert_application(candidate, payload):
    application_id = str(
        value_from(payload, "applicationId", "applyId", "ApplyId")
    )
    if not application_id:
        raise ValueError("投递数据缺少 applicationId。")
    if ExclusionMarker.objects.filter(application_id=application_id).exists():
        return None
    position_id = str(value_from(payload, "positionId", "jobId", "JobId"))
    requisition_id = str(value_from(payload, "requisitionId", "requirementId"))
    if not requisition_id:
        requisition_id = str(field_value(payload, "RecruitRequirementId"))
    position_name = value_from(payload, "positionName", "jobName", "JobName", default="未命名岗位")
    position = None
    if position_id:
        position = Position.objects.filter(beisen_position_id=position_id).first()
    if not position and requisition_id:
        position = Position.objects.filter(requisition_id=requisition_id).first()
    if not position:
        position = Position.objects.create(
            beisen_position_id=position_id,
            requisition_id=requisition_id,
            name=position_name,
            position_type=value_from(payload, "positionType", "jobType"),
            source_payload=payload,
            last_synced_at=timezone.now(),
        )
    defaults = {
        "candidate": candidate,
        "position": position,
        "source_type": Application.SourceType.BEISEN,
        "source_channel": application_channel(payload, candidate),
        "application_status": value_from(
            payload,
            "applicationStatus",
            "status",
            "processStatusId",
            default=field_value(
                payload,
                "ApplicationStatus",
                "ProcessStatus",
                "Status",
                prefer_text=True,
            ),
        ),
        "source_payload": payload,
    }
    applied_at = value_from(
        payload,
        "appliedTime",
        "applyDate",
        default=field_value(
            payload,
            "AppliedTime",
            "ApplyDate",
            "SubmissionDate",
            "InitialSubmissionDate",
            "BelongSubmissionDate",
            "LastSubmissionDate",
            "CreatedTime",
        ),
    )
    if applied_at:
        from django.utils.dateparse import parse_datetime

        parsed_applied_at = parse_datetime(str(applied_at))
        if parsed_applied_at and timezone.is_naive(parsed_applied_at):
            parsed_applied_at = timezone.make_aware(
                parsed_applied_at, timezone.get_default_timezone()
            )
        defaults["applied_at"] = parsed_applied_at
    application, _ = Application.objects.update_or_create(
        application_id=application_id, defaults=defaults
    )
    recommendation = (
        Application.objects.visible()
        .filter(
            candidate=candidate,
            position=position,
            source_type=Application.SourceType.TALENT,
        )
        .exclude(pk=application.pk)
        .order_by("-created_at")
        .first()
    )
    if recommendation and application.linked_application_id != recommendation.pk:
        application.linked_application = recommendation
        application.save(update_fields=["linked_application"])
    return application


def synchronize_records(
    profiles: Iterable[dict],
    application_map: dict[str, list[dict]],
    module_map=None,
    should_cancel=None,
):
    candidates = 0
    applications = 0
    failures = []
    for profile in profiles:
        if should_cancel and should_cancel():
            raise SyncCancelled
        try:
            applicant_id = str(value_from(profile, "applicantId", "ApplicantId", "id"))
            candidate = upsert_candidate(profile, (module_map or {}).get(applicant_id))
            candidates += 1
            for payload in application_map.get(candidate.applicant_id, []):
                if upsert_application(candidate, payload):
                    applications += 1
        except Exception as exc:
            failures.append(str(exc))
    return {
        "candidates": candidates,
        "applications": applications,
        "failures": failures,
    }


def upsert_positions(payload):
    from recruitment.services.position_matching import apply_match_suggestion

    count = 0
    for item in extract_items(payload):
        position_id = str(value_from(item, "positionId", "jobId", "id"))
        requisition_id = str(value_from(item, "requisitionId", "requirementId"))
        if not position_id and not requisition_id:
            continue
        status_value = str(value_from(item, "status", "positionStatus")).lower()
        status = position_status(status_value)
        position = Position.objects.filter(beisen_position_id=position_id).first()
        if not position and requisition_id:
            position = Position.objects.filter(requisition_id=requisition_id).first()
        position_type = list_text(
            value_from(item, "positionType", "jobType")
        )
        defaults = {
            "beisen_position_id": position_id,
            "requisition_id": requisition_id,
            "name": value_from(
                item,
                "positionName",
                "jobName",
                "jobTitle",
                "name",
                default="未命名岗位",
            ),
            "position_type": position_type,
            "source_jd": position_jd(item),
            "source_payload": item,
            "status_source": Position.StatusSource.BEISEN,
            "last_synced_at": timezone.now(),
        }
        if not position or not position.manual_status_override:
            defaults["status"] = status
        if position:
            for field, value in defaults.items():
                setattr(position, field, value)
            position.save()
        else:
            position = Position.objects.create(**defaults)
        apply_match_suggestion(position)
        count += 1
    return count


def position_change_counts(payload):
    new_count = 0
    jd_update_count = 0
    for item in extract_items(payload):
        position_id = str(value_from(item, "positionId", "jobId", "id"))
        requisition_id = str(value_from(item, "requisitionId", "requirementId"))
        position = Position.objects.filter(beisen_position_id=position_id).first()
        if not position and requisition_id:
            position = Position.objects.filter(requisition_id=requisition_id).first()
        if not position:
            new_count += 1
        elif (position.source_jd or "").strip() != position_jd(item).strip():
            jd_update_count += 1
    return new_count, jd_update_count


def position_status(status_value):
    if status_value in {
        "0",
        "2",
        "-1",
        "closed",
        "inactive",
        "historical",
        "已关闭",
        "历史",
    }:
        return Position.Status.HISTORICAL
    return Position.Status.ACTIVE


def position_jd(item):
    direct = value_from(item, "jd", "jobDescription", "description")
    if direct:
        return str(direct)
    sections = []
    for title, key in (
        ("岗位职责", "duty"),
        ("任职要求", "require"),
        ("招聘标准", "recruitmentStandard"),
    ):
        value = item.get(key)
        if isinstance(value, str):
            value = value.strip()
            try:
                UUID(value)
            except ValueError:
                value = re.sub(
                    rf"(?m)^[ \t]*{re.escape(title)}[ \t]*(?:(?:[:：])[ \t]*|(?=\r?$))",
                    "",
                    value,
                    count=1,
                ).lstrip()
            else:
                value = ""
        if value not in (None, "", [], {}):
            sections.append(f"{title}\n{value}")
    return "\n\n".join(sections)


def filename_from_file_payload(data, url):
    filename = value_from(data, "fileName", "filename", "name")
    if filename:
        return Path(str(filename)).name
    for source in (data.get("dfsPath"), url):
        if not source:
            continue
        path = unquote(urlparse(str(source)).path)
        if Path(path).name:
            return Path(path).name
    return "resume"


def file_info(payload):
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if isinstance(data, list):
        data = data[0] if data else {}
    url = value_from(data, "downloadUrl", "url", "fileUrl")
    return {
        "url": url,
        "filename": filename_from_file_payload(data, url),
        "mime_type": value_from(data, "contentType", "mimeType"),
    }


def sync_resume_files(candidate, client):
    origin = file_info(client.get_resume_file_info(candidate.applicant_id, origin=True))
    if not origin["url"]:
        return None, False
    content, response_type = client.download_file(origin["url"])
    resume, created = save_resume_bytes(
        candidate,
        content,
        ensure_filename(origin["filename"], origin["mime_type"] or response_type, content),
        origin["mime_type"] or response_type,
    )
    try:
        standard = file_info(
            client.get_resume_file_info(candidate.applicant_id, origin=False)
        )
        if standard["url"] and not resume.standard_pdf:
            pdf_content, _ = client.download_file(standard["url"])
            attach_standard_pdf(
                resume,
                pdf_content,
                ensure_filename(
                    standard["filename"] or "standard-resume",
                    "application/pdf",
                    pdf_content,
                ),
            )
            if resume.source_payload.pop("standard_file_error", None) is not None:
                resume.save(update_fields=["source_payload"])
    except Exception as exc:
        resume.source_payload["standard_file_error"] = safe_sync_error(exc)
        resume.save(update_fields=["source_payload"])
    if created or not resume.extracted_text:
        parse_resume(resume)
    Application.objects.visible().filter(candidate=candidate).update(
        current_resume=resume
    )
    if created:
        for user in User.objects.filter(is_active=True):
            notify(
                user,
                "同步到新简历",
                f"{candidate} 的简历文件已更新。",
                target_url=f"/recruitment/candidates/{candidate.pk}/",
            )
    return resume, created


def ensure_filename(filename, mime_type, content):
    path = Path(filename or "resume")
    if path.suffix:
        return path.name
    normalized_type = (mime_type or "").split(";", 1)[0].strip().lower()
    extension = {
        "application/pdf": ".pdf",
        "text/html": ".html",
        "application/xhtml+xml": ".html",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }.get(normalized_type, "")
    if not extension and content.startswith(b"%PDF"):
        extension = ".pdf"
    return f"{path.name}{extension}"


def safe_sync_error(exc):
    if isinstance(exc, Exception):
        message = str(exc)
    else:
        message = str(exc)
    message = re.sub(r"([?&](?:sig|token|access_token)[^=\s]*)=[^&\s'\"]+", r"\1=<redacted>", message)
    message = re.sub(r"\?[^\s'\"]+", "?<redacted>", message)
    return message[:500]


class SyncCancelled(Exception):
    pass


def sync_cancellation_requested(sync_job_id):
    return SyncJob.objects.filter(
        pk=sync_job_id,
        status__in=[
            SyncJob.Status.CANCELLATION_REQUESTED,
            SyncJob.Status.CANCELLED,
        ],
    ).exists()


def run_sync_job(sync_job, client):
    if sync_cancellation_requested(sync_job.pk):
        sync_job.status = SyncJob.Status.CANCELLED
        sync_job.finished_at = timezone.now()
        sync_job.save(update_fields=["status", "finished_at"])
        return sync_job
    sync_job.status = SyncJob.Status.RUNNING
    sync_job.started_at = timezone.now()
    sync_job.save(update_fields=["status", "started_at"])
    profiles = []
    application_map = {}
    module_map = {}
    position_ids = set()
    initial_rule_task_ids = []
    try:
        for applicant_ids in client.iter_applicant_ids(
            sync_job.window_start, sync_job.window_end, 2 if sync_job.sync_type == SyncJob.SyncType.FULL else 1
        ):
            if sync_cancellation_requested(sync_job.pk):
                raise SyncCancelled
            for applicant_chunk in chunks(applicant_ids, 100):
                if sync_cancellation_requested(sync_job.pk):
                    raise SyncCancelled
                profile_payload = client.get_profiles(applicant_chunk)
                application_payload = client.get_applications(applicant_chunk)
                for application in extract_items(application_payload):
                    applicant_id = str(
                        value_from(application, "applicantId", "ApplicantId")
                    )
                    if not applicant_id:
                        continue
                    application_map.setdefault(applicant_id, []).append(application)
                    position_id = str(
                        value_from(
                            application,
                            "positionId",
                            "jobId",
                            "JobId",
                        )
                    )
                    if position_id:
                        position_ids.add(position_id)
                for module_code in settings.ITALENT_RESUME_MODULES:
                    if sync_cancellation_requested(sync_job.pk):
                        raise SyncCancelled
                    module_payload = client.get_resume_module(
                        applicant_chunk, module_code
                    )
                    for item in extract_items(module_payload):
                        applicant_id = str(
                            value_from(item, "applicantId", "ApplicantId")
                        )
                        module_map.setdefault(applicant_id, {})[module_code] = item
                for profile in extract_items(profile_payload):
                    profiles.append(profile)
        position_count = 0
        new_position_count = 0
        updated_position_jd_count = 0
        get_positions = getattr(client, "get_positions", lambda position_ids: {})
        for position_chunk in chunks(sorted(position_ids), 100):
            if sync_cancellation_requested(sync_job.pk):
                raise SyncCancelled
            position_payload = get_positions(position_chunk)
            new_count, update_count = position_change_counts(position_payload)
            new_position_count += new_count
            updated_position_jd_count += update_count
            position_count += upsert_positions(position_payload)
        rule_actor = (
            sync_job.requested_by
            or User.objects.filter(is_active=True, role=User.Role.ADMIN).first()
            or User.objects.filter(is_active=True).first()
        )
        if settings.AUTO_GENERATE_INITIAL_RULES:
            synced_positions = Position.objects.filter(
                beisen_position_id__in=position_ids,
                status=Position.Status.ACTIVE,
            )
            for position in synced_positions:
                if sync_cancellation_requested(sync_job.pk):
                    raise SyncCancelled
                if position.rule_versions.exists() or position.jd_decisions.exists():
                    continue
                initialization, created = (
                    PositionRuleInitialization.objects.get_or_create(
                        sync_job=sync_job,
                        position=position,
                        defaults={"requested_by": rule_actor},
                    )
                )
                if created or initialization.status in {
                    PositionRuleInitialization.Status.QUEUED,
                    PositionRuleInitialization.Status.FAILED,
                }:
                    initial_rule_task_ids.append(initialization.pk)
        result = synchronize_records(
            profiles,
            application_map,
            module_map,
            should_cancel=lambda: sync_cancellation_requested(sync_job.pk),
        )
        file_failures = []
        parse_issues = []
        preview_issues = []
        file_updates = 0
        applicant_ids = [
            str(value_from(profile, "applicantId", "ApplicantId", "id"))
            for profile in profiles
        ]
        eligible_candidates = (
            Candidate.objects.filter(
                applicant_id__in=applicant_ids,
                applications__deleted_at__isnull=True,
                applications__position__status=Position.Status.ACTIVE,
            )
            .distinct()
        )
        eligible_candidate_ids = set(
            eligible_candidates.values_list("applicant_id", flat=True)
        )
        for candidate in eligible_candidates:
            if sync_cancellation_requested(sync_job.pk):
                raise SyncCancelled
            try:
                resume, created = sync_resume_files(candidate, client)
                file_updates += int(created)
                standard_file_error = (
                    resume.source_payload.get("standard_file_error")
                    if resume and isinstance(resume.source_payload, dict)
                    else ""
                )
                if standard_file_error:
                    preview_issues.append(
                        {
                            "applicant_id": candidate.applicant_id,
                            "error": safe_sync_error(standard_file_error),
                        }
                    )
                if resume and resume.parse_status in {
                    ResumeVersion.ParseStatus.FAILED,
                    ResumeVersion.ParseStatus.LOW_QUALITY,
                    ResumeVersion.ParseStatus.UNSUPPORTED,
                }:
                    parse_issues.append(
                        {
                            "applicant_id": candidate.applicant_id,
                            "status": resume.parse_status,
                            "error": safe_sync_error(resume.parse_error),
                        }
                    )
            except Exception as exc:
                file_failures.append(
                    {
                        "applicant_id": candidate.applicant_id,
                        "error": safe_sync_error(exc),
                    }
                )
        result["positions"] = position_count
        result["new_positions"] = new_position_count
        result["updated_position_jds"] = updated_position_jd_count
        result["initial_rule_tasks_created"] = len(initial_rule_task_ids)
        result["resume_file_updates"] = file_updates
        result["resume_file_candidates"] = len(eligible_candidate_ids)
        result["resume_file_skipped_historical"] = len(
            set(applicant_ids) - eligible_candidate_ids
        )
        result["record_failures"] = [
            {"error": safe_sync_error(value)} for value in result.pop("failures")
        ]
        result["file_failures"] = file_failures
        result["parse_issues"] = parse_issues
        result["preview_issues"] = preview_issues
        result["failure_summary"] = {
            "record": len(result["record_failures"]),
            "file": len(file_failures),
            "parse": len(parse_issues),
            "preview": len(preview_issues),
        }
        sync_job.total_count = len(profiles)
        sync_job.success_count = result["candidates"]
        sync_job.failure_count = sum(result["failure_summary"].values())
        sync_job.metadata = result
        sync_job.status = (
            SyncJob.Status.SUCCESS
            if sync_job.failure_count == 0
            else SyncJob.Status.PARTIAL
        )
    except SyncCancelled:
        sync_job.status = SyncJob.Status.CANCELLED
        sync_job.error_message = ""
        PositionRuleInitialization.objects.filter(
            sync_job=sync_job,
            status__in=[
                PositionRuleInitialization.Status.QUEUED,
                PositionRuleInitialization.Status.CANCELLATION_REQUESTED,
            ],
        ).update(
            status=PositionRuleInitialization.Status.CANCELLED,
            finished_at=timezone.now(),
        )
    except Exception as exc:
        sync_job.status = SyncJob.Status.FAILED
        sync_job.error_message = safe_sync_error(exc)
    sync_job.finished_at = timezone.now()
    sync_job.save(
        update_fields=[
            "total_count",
            "success_count",
            "failure_count",
            "metadata",
            "status",
            "error_message",
            "finished_at",
        ]
    )
    has_changes = bool(
        sync_job.total_count > 0
        or sync_job.success_count > 0
        or sync_job.metadata.get("applications", 0)
        or sync_job.metadata.get("positions", 0)
        or sync_job.metadata.get("new_positions", 0)
        or sync_job.metadata.get("updated_position_jds", 0)
        or sync_job.metadata.get("resume_file_updates", 0)
        or sync_job.metadata.get("initial_rule_tasks_created", 0)
        or sync_job.failure_count > 0
        or sync_job.error_message
        or sync_job.status not in {SyncJob.Status.SUCCESS, SyncJob.Status.PARTIAL}
    )
    is_scheduled = (sync_job.requested_by_id is None)

    if is_scheduled and not has_changes and sync_job.status == SyncJob.Status.SUCCESS:
        job_pk = sync_job.pk
        sync_job.delete()
        sync_job.pk = job_pk
        return sync_job

    if sync_job.status in {SyncJob.Status.SUCCESS, SyncJob.Status.PARTIAL}:
        for initialization_id in initial_rule_task_ids:
            dispatch_task(
                execute_position_rule_initialization,
                initialization_id,
            )
        if not is_scheduled or has_changes:
            for user in User.objects.filter(is_active=True):
                configuration_message = ""
                if sync_job.metadata.get("new_positions") or sync_job.metadata.get(
                    "updated_position_jds"
                ) or sync_job.metadata.get("initial_rule_tasks_created"):
                    configuration_message = (
                        f" 新岗位 {sync_job.metadata.get('new_positions', 0)} 个，"
                        f"岗位说明更新 {sync_job.metadata.get('updated_position_jds', 0)} 个，"
                        f"已创建岗位初始化任务 "
                        f"{sync_job.metadata.get('initial_rule_tasks_created', 0)} 个。"
                    )
                    if sync_job.metadata.get("updated_position_jds"):
                        configuration_message += " 请前往岗位配置处理。"
                notify(
                    user,
                    "北森同步完成",
                    (
                        f"同步候选人 {sync_job.success_count} 人，"
                        f"新增简历 {sync_job.metadata.get('resume_file_updates', 0)} 份，"
                        f"问题 {sync_job.failure_count} 项。"
                        f"{configuration_message}"
                    ),
                    target_url=(
                        (
                            f"/recruitment/sync/{sync_job.pk}/"
                            "position-initializations/"
                        )
                        if sync_job.metadata.get("initial_rule_tasks_created")
                        else (
                            "/recruitment/position-configuration/"
                            if sync_job.metadata.get("updated_position_jds")
                            else "/recruitment/sync/"
                        )
                    ),
                )
    return sync_job
