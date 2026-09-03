from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from analysis.integrations.model import ModelGateway
from analysis.models import (
    AnalysisItem,
    AnalysisReport,
    ModelUsage,
    ModelVersion,
    PromptVersion,
)
from recruitment.models import ResumeVersion
from recruitment.services.common import notify

from .prompts import DEFAULT_SYSTEM_PROMPT, build_analysis_prompt
from .redaction import redact_resume_text
from .schema import validate_report_payload


def get_runtime_versions():
    prompt, _ = PromptVersion.objects.get_or_create(
        version="system-v1",
        defaults={"content": DEFAULT_SYSTEM_PROMPT, "is_active": True},
    )
    update_fields = []
    if not prompt.is_active:
        prompt.is_active = True
        update_fields.append("is_active")
    if prompt.content != DEFAULT_SYSTEM_PROMPT and prompt.content != "system":
        prompt.content = DEFAULT_SYSTEM_PROMPT
        update_fields.append("content")
    if update_fields:
        prompt.save(update_fields=update_fields)
    provider = "configured"
    model, _ = ModelVersion.objects.get_or_create(
        provider=provider,
        name=settings.MODEL_NAME or "unconfigured",
        version=settings.MODEL_NAME or "unconfigured",
        defaults={
            "is_active": True,
            "input_cost_per_million": settings.MODEL_INPUT_COST_PER_MILLION,
            "output_cost_per_million": settings.MODEL_OUTPUT_COST_PER_MILLION,
        },
    )
    return prompt, model


def calculate_cost(model, input_tokens, output_tokens):
    million = Decimal("1000000")
    input_rate = Decimal(str(model.input_cost_per_million))
    output_rate = Decimal(str(model.output_cost_per_million))
    return (
        Decimal(input_tokens) * input_rate / million
        + Decimal(output_tokens) * output_rate / million
    ).quantize(Decimal("0.0001"))


def analyze_item(item, gateway=None):
    item = (
        AnalysisItem.objects.select_related(
            "application__candidate",
            "application__position",
            "resume_version",
            "rule_version",
            "job__requested_by",
        )
        .get(pk=item.pk)
    )
    if item.resume_version.parse_status != ResumeVersion.ParseStatus.SUCCESS:
        item.status = AnalysisItem.Status.PARSE_FAILED
        item.error_message = item.resume_version.parse_error or "简历尚未成功解析。"
        item.finished_at = timezone.now()
        item.save(update_fields=["status", "error_message", "finished_at"])
        return None
    item.status = AnalysisItem.Status.RUNNING
    item.started_at = timezone.now()
    item.save(update_fields=["status", "started_at"])
    prompt_version, model_version = get_runtime_versions()
    resume_text = redact_resume_text(
        item.resume_version.extracted_text,
        item.application.candidate.name,
    )
    stale = item.resume_version.created_at < timezone.now() - timedelta(days=730)
    result = (gateway or ModelGateway()).analyze(
        prompt_version.content,
        build_analysis_prompt(item.rule_version, resume_text, stale=stale),
    )
    payload = validate_report_payload(
        result["payload"], item.rule_version.rating_thresholds
    )
    if stale:
        payload["interview_focus"].append("该简历已超过 24 个月未更新，请核实当前经历。")
    cost = calculate_cost(
        model_version, result["input_tokens"], result["output_tokens"]
    )
    with transaction.atomic():
        item = AnalysisItem.objects.select_for_update(of=("self",)).select_related(
            "job__requested_by", "application__candidate", "application__position"
        ).get(pk=item.pk)
        report = AnalysisReport.objects.create(
            item=item,
            prompt_version=prompt_version,
            model_version=model_version,
            score=payload["score"],
            rating=payload["rating"],
            hard_requirement_results=payload["hard_requirement_results"],
            dimension_results=payload["dimension_results"],
            strengths=payload["strengths"],
            risks=payload["risks"],
            missing_information=payload["missing_information"],
            interview_focus=payload["interview_focus"],
            interview_questions=payload["interview_questions"],
            raw_response=payload,
            input_tokens=result["input_tokens"],
            output_tokens=result["output_tokens"],
            estimated_cost=cost,
        )
        ModelUsage.objects.create(
            model_version=model_version,
            user=item.job.requested_by,
            position=item.application.position,
            input_tokens=result["input_tokens"],
            output_tokens=result["output_tokens"],
            estimated_cost=cost,
        )
        item.status = AnalysisItem.Status.SUCCESS
        item.finished_at = timezone.now()
        item.error_message = ""
        item.save(update_fields=["status", "finished_at", "error_message"])
    notify(
        item.job.requested_by,
        "AI 分析已完成",
        f"{item.application.candidate} · {item.application.position}：{report.score} 分",
        target_url=f"/analysis/reports/{report.pk}/",
    )
    return report
