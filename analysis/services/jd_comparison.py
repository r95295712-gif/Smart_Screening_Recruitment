import json
import re
from decimal import Decimal

from analysis.integrations.model import ModelGateway
from analysis.models import ModelUsage, ModelVersion


JD_DIFF_SYSTEM_PROMPT = """你是专业的招聘岗位说明对比专家。请客观对比给定的【北森岗位说明】与【参考资料岗位说明】，结构化总结两者的关键差异。
输出 JSON 对象，包含 summary 字段。
summary 请使用清晰、易读的中文纯文本格式（严禁使用任何 Markdown 符号如 ###、##、#、**、*、`、- 等），按照以下结构分段输出（若某项无显著差异，请简明注明“无明显差异”）：

【核心职责差异】
1. 对比双方在日常职责、业务重心及管理职责上的具体差异。

【硬性要求差异】
1. 对比学历、专业、最低工作年限等硬性门槛要求的差异。

【专业技能与经验差异】
1. 对比技术栈、专业工具、项目经验及业务知识要求的差异。

【加分项与优先条件】
1. 对比优先考虑条件、加分技能及附加要求的差异。

【人工确认要点建议】
1. 提示 HR / 业务负责人在确认最终 JD 时需要特别注意核对的要点。

请保持条理清晰、文字通顺，适合直接纯文本阅读。"""


def clean_diff_summary_text(text):
    if not text:
        return ""
    cleaned = text
    # Convert markdown headers to 【...】
    cleaned = re.sub(r"^[#\s]*###?\s*(?:[0-9]+[.\s、]*)?([^\n]+)", r"【\1】", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^[#\s]*##\s*(?:[0-9]+[.\s、]*)?([^\n]+)", r"【\1】", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^[#\s]*#\s*(?:[0-9]+[.\s、]*)?([^\n]+)", r"【\1】", cleaned, flags=re.MULTILINE)
    # Remove bold / italic / code markers
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    # Normalize bullet points to clean dash or numbering
    cleaned = re.sub(r"^\s*[-*+]\s+", "• ", cleaned, flags=re.MULTILINE)
    # Clean redundant empty lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


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
        raw_summary = str(result["payload"].get("summary", "")).strip()
        summary = clean_diff_summary_text(raw_summary)
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

