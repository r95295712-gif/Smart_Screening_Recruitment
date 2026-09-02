import json
import re
from decimal import Decimal

from analysis.integrations.model import ModelGateway
from analysis.models import ModelUsage, ModelVersion


JD_MERGE_SYSTEM_PROMPT = """你是资深招聘与岗位分析专家。请将给定的【北森岗位说明】与【参考资料岗位说明】进行智能融合，提炼生成一份专业、精炼、无冗余的统一岗位说明。

【融合与冲突消歧原则】：
1. 结构规范：统一整理为两大核心模块：
   岗位职责：
   1. ...
   任职要求：
   1. ...
   （若有特殊补充说明或明确的加分优先项，可在文末增加【加分与其它说明：】）
2. 去除重复与同类合并：
   - 彻底合并两份材料中重复、相近或同义的职责与要求（如多处出现的“本科学历”、“英语六级”、“沟通能力”、“产品敏锐度”等，只保留一条精炼表述，严禁机械重复拼接）。
3. 冲突消解（严格保留高标准与合理兼顾）：
   - 当两份说明在学历、外语、专业技能或硬性门槛上存在差异时，一律保留更高标准（例如：专科与本科取本科；英语四级与六级取六级）。
   - 当在工作年限或专项经验上存在不同（例如：“工作满3年以上”与“工作满2年以上，有相关品类开发经验”），必须保留更高年限标准，同时融合同类经验的专项优先说明（例如：“工作满3年以上（其中具备亚马逊家居类目产品线开发经验者优先）”）。
4. 格式要求：
   - 严格输出 JSON 对象，包含 "merged_jd" 字段，值为上述合并后的纯文本内容。
   - 纯文本中严禁包含任何 Markdown 格式符号（如不要使用 **加粗** 或 ` 或 ``` 代码块），条目编号统一使用阿拉伯数字（1. 2. 3.）。
"""


def clean_merged_jd_text(text):
    if not text:
        return ""
    cleaned = text
    # Remove markdown formatting if any
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"^[#\s]*###?\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


from django.conf import settings


def get_runtime_model():
    model = ModelVersion.objects.filter(is_active=True).first()
    if not model and getattr(settings, "MODEL_NAME", ""):
        model, _ = ModelVersion.objects.get_or_create(
            provider="configured",
            name=settings.MODEL_NAME,
            version=settings.MODEL_NAME,
            defaults={
                "is_active": True,
                "input_cost_per_million": getattr(settings, "MODEL_INPUT_COST_PER_MILLION", Decimal("0")),
                "output_cost_per_million": getattr(settings, "MODEL_OUTPUT_COST_PER_MILLION", Decimal("0")),
            },
        )
    return model


def create_ai_merged_jd(position, document_position, actor, gateway=None):
    beisen_text = (position.source_jd or "").strip()
    doc_text = (document_position.jd if document_position else "").strip()

    # If only one source exists or both are identical, no need to call LLM
    if not doc_text:
        return beisen_text, "source"
    if not beisen_text:
        return doc_text, "source"
    if beisen_text == doc_text:
        return beisen_text, "source"

    model = get_runtime_model()
    if not model:
        raise ValueError("当前没有可用的模型配置。")

    prompt = json.dumps(
        {
            "position": position.name,
            "beisen_jd": beisen_text,
            "document_position": document_position.title if document_position else "",
            "document_jd": doc_text,
        },
        ensure_ascii=False,
    )

    try:
        result = (gateway or ModelGateway()).analyze(JD_MERGE_SYSTEM_PROMPT, prompt)
        raw_merged = str(result["payload"].get("merged_jd", "")).strip()
        merged_jd = clean_merged_jd_text(raw_merged)
        if not merged_jd:
            raise ValueError("模型未返回可用的合并岗位说明。")

        input_tokens = int(result.get("input_tokens", 0))
        output_tokens = int(result.get("output_tokens", 0))
        cost = (
            Decimal(input_tokens) * model.input_cost_per_million
            + Decimal(output_tokens) * model.output_cost_per_million
        ) / Decimal(1_000_000)

        purpose = getattr(ModelUsage.Purpose, "JD_MERGE", ModelUsage.Purpose.JD_DIFF)
        ModelUsage.objects.create(
            model_version=model,
            user=actor,
            position=position,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=cost,
            purpose=purpose,
        )
        return merged_jd, str(model)
    except Exception:
        purpose = getattr(ModelUsage.Purpose, "JD_MERGE", ModelUsage.Purpose.JD_DIFF)
        ModelUsage.objects.create(
            model_version=model,
            user=actor,
            position=position,
            success=False,
            purpose=purpose,
        )
        raise
