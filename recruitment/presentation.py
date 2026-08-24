import re
from pathlib import Path

from django.db.models import Prefetch

from .models import Application, Candidate


def safe_filename_part(value, fallback):
    cleaned = re.sub(r'[\\/:*?"<>|]+', "-", str(value or fallback))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    return cleaned or fallback


def resume_display_name(candidate, position=None, suffix=".pdf"):
    candidate_name = safe_filename_part(candidate.name, "候选人")
    parts = [candidate_name]
    if position:
        parts.append(safe_filename_part(position.name, "应聘岗位"))
    parts.append("简历")
    extension = suffix if str(suffix).startswith(".") else f".{suffix}"
    return "-".join(parts) + extension.lower()


def resume_source_suffix(resume):
    return Path(resume.original_filename or "").suffix or ".pdf"


def resume_position(resume):
    application = (
        resume.current_for_applications.visible()
        .select_related("position")
        .first()
    )
    return application.position if application else None


SYNC_ISSUE_GROUPS = (
    (
        "record_failures",
        "数据记录未完整处理",
        "候选人或投递数据在本次同步中未完整保存。",
        "建议重新执行相同时间范围的同步。",
        False,
    ),
    (
        "file_failures",
        "简历文件暂未获取成功",
        "连接北森获取简历文件时未能完成。",
        "可以直接重新获取该候选人的简历。",
        True,
    ),
    (
        "parse_issues",
        "简历内容暂未完整识别",
        "简历文件已经保存，但可识别的文字内容不足。",
        "请查看原简历；必要时重新获取或由 HR 人工确认。",
        False,
    ),
    (
        "preview_issues",
        "简历在线预览文件暂未更新",
        "候选人和简历数据已经同步，但在线预览文件未下载完成。",
        "可以直接重新获取预览，无需重新同步全部候选人。",
        True,
    ),
)


def _sync_issue_reason(error):
    normalized = str(error or "").lower()
    if "10013" in normalized:
        return "本地服务当前没有连接北森的网络权限。"
    if "unexpected_eof" in normalized or "ssl" in normalized:
        return "连接北森下载文件时临时中断。"
    if "timeout" in normalized or "timed out" in normalized:
        return "连接北森时等待时间过长，本次下载未完成。"
    if "json" in normalized or "nonetype" in normalized:
        return "北森返回的数据暂时无法处理，本次同步未完成。"
    return ""


def build_sync_issue_rows(job):
    metadata = job.metadata if isinstance(job.metadata, dict) else {}
    raw_issues = []
    applicant_ids = set()
    for key, title, default_reason, suggestion, can_retry in SYNC_ISSUE_GROUPS:
        values = metadata.get(key, [])
        if not isinstance(values, list):
            continue
        for value in values:
            issue = value if isinstance(value, dict) else {"error": value}
            applicant_id = str(issue.get("applicant_id") or "").strip()
            if applicant_id:
                applicant_ids.add(applicant_id)
            raw_issues.append(
                {
                    "title": title,
                    "default_reason": default_reason,
                    "reason": (
                        _sync_issue_reason(issue.get("error")) or default_reason
                    ),
                    "suggestion": suggestion,
                    "can_retry": can_retry,
                    "applicant_id": applicant_id,
                }
            )

    candidates = Candidate.objects.filter(applicant_id__in=applicant_ids).prefetch_related(
        Prefetch(
            "applications",
            queryset=Application.objects.visible().select_related("position"),
            to_attr="sync_issue_applications",
        )
    )
    candidates_by_applicant_id = {
        candidate.applicant_id: candidate for candidate in candidates
    }
    rows = []
    for issue in raw_issues:
        candidate = candidates_by_applicant_id.get(issue.pop("applicant_id"))
        positions = []
        if candidate:
            positions = list(
                dict.fromkeys(
                    application.position.name
                    for application in candidate.sync_issue_applications
                )
            )
        issue["candidate"] = candidate
        issue["candidate_name"] = candidate.name if candidate else "未能识别候选人"
        issue["positions"] = "、".join(positions) or "-"
        rows.append(issue)

    if job.error_message:
        rows.insert(
            0,
            {
                "title": "同步任务未完成",
                "default_reason": "本次同步任务在连接外部服务时中断。",
                "reason": _sync_issue_reason(job.error_message)
                or "本次同步任务在连接外部服务时中断。",
                "suggestion": "处理连接问题后，重新执行相同时间范围的同步。",
                "can_retry": False,
                "candidate": None,
                "candidate_name": "本次同步任务",
                "positions": "-",
            },
        )
    return rows
