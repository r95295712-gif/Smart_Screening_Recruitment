from django.db import transaction

from analysis.models import (
    AnalysisItem,
    AnalysisJob,
    AnalysisReport,
    ModelVersion,
    PositionRuleVersion,
    PromptVersion,
)
from recruitment.models import Application, Position, ResumeVersion
from recruitment.services.configuration import require_analysis_configuration


class AnalysisJobError(ValueError):
    pass


@transaction.atomic
def create_analysis_job(position, application_ids, user, force_reason=""):
    if position.status != Position.Status.ACTIVE:
        raise AnalysisJobError("历史岗位不能发起新的 AI 分析。")
    try:
        require_analysis_configuration(position)
    except ValueError as exc:
        raise AnalysisJobError(str(exc)) from exc
    ids = list(dict.fromkeys(application_ids))
    if not ids:
        raise AnalysisJobError("请至少选择一份简历。")
    if len(ids) > 20:
        raise AnalysisJobError("一期单批最多处理 20 份简历。")
    rule = PositionRuleVersion.objects.filter(
        position=position, status=PositionRuleVersion.Status.PUBLISHED
    ).first()
    if not rule:
        raise AnalysisJobError("该岗位尚未发布评估规则。")
    applications = list(
        Application.objects.visible()
        .filter(pk__in=ids, position=position)
        .select_related("current_resume")
    )
    if len(applications) != len(ids):
        raise AnalysisJobError("选择中包含无效或不属于当前岗位的投递。")
    for application in applications:
        if not application.current_resume:
            raise AnalysisJobError(f"{application.candidate} 缺少简历文件。")
        if application.current_resume.parse_status != ResumeVersion.ParseStatus.SUCCESS:
            raise AnalysisJobError(f"{application.candidate} 的简历尚未成功解析。")
    job = AnalysisJob.objects.create(
        position=position,
        requested_by=user,
        total_count=len(applications),
    )
    prompt = PromptVersion.objects.filter(is_active=True).first()
    model = ModelVersion.objects.filter(is_active=True).first()
    for application in applications:
        reused = None
        if not force_reason and prompt and model:
            reused = (
                AnalysisReport.objects.filter(
                    item__application=application,
                    item__resume_version=application.current_resume,
                    item__rule_version=rule,
                    prompt_version=prompt,
                    model_version=model,
                )
                .order_by("-created_at")
                .first()
            )
        item = AnalysisItem.objects.create(
            job=job,
            application=application,
            resume_version=application.current_resume,
            rule_version=rule,
            force_reanalysis_reason=force_reason,
            reused_report=reused,
            status=AnalysisItem.Status.SUCCESS if reused else AnalysisItem.Status.QUEUED,
        )
        if reused:
            item.finished_at = reused.created_at
            item.save(update_fields=["finished_at"])
    return job
