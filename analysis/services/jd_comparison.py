import json
from decimal import Decimal

from analysis.integrations.model import ModelGateway
from analysis.models import ModelUsage, ModelVersion


JD_DIFF_SYSTEM_PROMPT = """你是招聘岗位说明对比助手。请只总结两份岗位说明在职责、硬性要求、经验、学历、技能和加分项上的差异，不替用户决定采用哪一份。输出 JSON，字段为 summary。"""


def create_ai_diff_summary(position, document_position, actor, gateway=None):
    model = ModelVersion.objects.filter(is_active=True).first()
    if not model:
        raise ValueError("当前没有可用的模型配置。")
    prompt = json.dumps(
        {
            "position": position.name,
            "beisen_jd": position.source_jd,
            "document_position": document_position.title if document_position else "",
            "document_jd": document_position.jd if document_position else "",
        },
        ensure_ascii=False,
    )
    try:
        result = (gateway or ModelGateway()).analyze(JD_DIFF_SYSTEM_PROMPT, prompt)
        summary = str(result["payload"].get("summary", "")).strip()
        if not summary:
            raise ValueError("模型未返回可用的差异摘要。")
        input_tokens = int(result.get("input_tokens", 0))
        output_tokens = int(result.get("output_tokens", 0))
        cost = (
            Decimal(input_tokens) * model.input_cost_per_million
            + Decimal(output_tokens) * model.output_cost_per_million
        ) / Decimal(1_000_000)
        ModelUsage.objects.create(
            model_version=model,
            user=actor,
            position=position,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=cost,
            purpose=ModelUsage.Purpose.JD_DIFF,
        )
        return summary, str(model)
    except Exception:
        ModelUsage.objects.create(
            model_version=model,
            user=actor,
            position=position,
            success=False,
            purpose=ModelUsage.Purpose.JD_DIFF,
        )
        raise

