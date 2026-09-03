import difflib
import json
import re

from django.db.models import Max
from django.db import transaction

from analysis.integrations.model import ModelGateway
from analysis.models import ModelUsage, ModelVersion, PositionRuleVersion
from recruitment.models import PositionConfiguration, PositionJdDecision
from recruitment.services.common import record_audit
from recruitment.services.configuration import confirm_jd


class RuleDraftError(ValueError):
    pass


class RuleGenerationCancelled(RuleDraftError):
    pass


RULE_SYSTEM_PROMPT = """你是招聘岗位规则整理助手。只根据岗位 JD 输出 JSON 草稿，不做候选人判断。JSON 必须包含 evaluation_jd、hard_requirements、dimensions、bonus_items、rating_thresholds。在提取 hard_requirements 时，年限、学历、资质等条件应提取为准入基准门槛（例如'1-3年'应表述为'具备1年以上相关经验（1-3年为佳）'），避免提取为封闭死板的绝对上限，确保后续高资历候选人正向兼容。dimensions 中每项包含 name、weight、description，weight 必须是 0 到 100 的整数且总和必须为 100。rating_thresholds 必须严格输出为 {"priority": 80, "review": 60} 这种结构，priority 和 review 只能是 0 到 100 的整数下限，禁止输出数组、区间、对象或文字。"""


def _score_value(value, label, default):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise RuleDraftError(f"{label}必须是 0 到 100 的数字。")
    if isinstance(value, dict):
        for key in ("min", "minimum", "lower", "start", "score", "value", "range"):
            if key in value:
                return _score_value(value[key], label, default)
        raise RuleDraftError(f"{label}格式无法识别，请重新生成草稿。")
    if isinstance(value, (list, tuple)):
        if not value:
            return default
        scores = [_score_value(item, label, default) for item in value]
        return min(scores)
    if isinstance(value, str):
        numbers = re.findall(r"\d+(?:\.\d+)?", value)
        if not numbers:
            raise RuleDraftError(f"{label}格式无法识别，请重新生成草稿。")
        score = int(float(numbers[0]))
    else:
        try:
            score = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuleDraftError(
                f"{label}必须是 0 到 100 的数字。"
            ) from exc
    if not 0 <= score <= 100:
        raise RuleDraftError(f"{label}必须在 0 到 100 之间。")
    return score


def validate_rule_payload(payload):
    if not isinstance(payload, dict):
        raise RuleDraftError("岗位规则草稿不是 JSON 对象。")
    hard_requirements = payload.get("hard_requirements", [])
    dimensions = payload.get("dimensions", [])
    bonus_items = payload.get("bonus_items", [])
    thresholds = payload.get("rating_thresholds", {})
    if not all(
        isinstance(value, list)
        for value in [hard_requirements, dimensions, bonus_items]
    ):
        raise RuleDraftError("岗位规则列表字段格式错误。")
    if not isinstance(thresholds, dict):
        raise RuleDraftError("推荐等级区间格式错误。")
    normalized_dimensions = []
    for item in dimensions:
        if not isinstance(item, dict):
            raise RuleDraftError("评分维度格式无法识别，请重新生成草稿。")
        normalized_item = dict(item)
        normalized_item["weight"] = _score_value(
            item.get("weight"),
            "评分维度权重",
            0,
        )
        normalized_dimensions.append(normalized_item)
    total_weight = sum(item["weight"] for item in normalized_dimensions)
    if dimensions and total_weight != 100:
        raise RuleDraftError("评分维度权重总和必须为 100。")
    priority = _score_value(
        thresholds.get("priority"),
        "优先推荐分数线",
        80,
    )
    review = _score_value(
        thresholds.get("review"),
        "建议复核分数线",
        60,
    )
    if priority <= review:
        raise RuleDraftError("优先推荐分数线必须高于建议复核分数线。")
    return {
        "evaluation_jd": str(payload.get("evaluation_jd", "")),
        "hard_requirements": hard_requirements,
        "dimensions": normalized_dimensions,
        "bonus_items": bonus_items,
        "rating_thresholds": {
            "priority": priority,
            "review": review,
        },
    }


def effective_position_jd(position):
    try:
        position.configuration
    except PositionConfiguration.DoesNotExist:
        return (position.evaluation_jd or position.source_jd).strip()
    decision = position.jd_decisions.filter(is_current=True).first()
    if not decision:
        raise RuleDraftError("请先确认岗位说明，再生成评估规则草稿。")
    return decision.confirmed_jd.strip()


def generate_rule_payload(position, gateway=None):
    effective_jd = effective_position_jd(position)
    if not effective_jd:
        raise RuleDraftError("该岗位尚无可用的系统评估 JD。")
    result = _generate_rule_result(position, effective_jd, gateway)
    return validate_rule_payload(result["payload"])


def _generate_rule_result(position, effective_jd, gateway=None):
    prompt = json.dumps(
        {
            "position": position.name,
            "source_jd": effective_jd,
            "constraints": [
                "敏感条件只能按 JD 明确表述整理，不得扩展或推测。",
                "每个评分维度给出 name、weight 和 description。",
                "输出仅为管理员可编辑草稿。",
            ],
        },
        ensure_ascii=False,
    )
    return (gateway or ModelGateway()).analyze(RULE_SYSTEM_PROMPT, prompt)


def _record_rule_usage(rule, actor, result):
    model = ModelVersion.objects.filter(is_active=True).first()
    if not model:
        return
    ModelUsage.objects.create(
        model_version=model,
        user=actor,
        position=rule.position,
        input_tokens=int(result.get("input_tokens", 0)),
        output_tokens=int(result.get("output_tokens", 0)),
        purpose=ModelUsage.Purpose.RULE_DRAFT,
    )


def create_generated_rule(position, actor, gateway=None, should_cancel=None):
    if should_cancel and should_cancel():
        raise RuleGenerationCancelled("岗位规则草稿生成已取消。")
    selected_gateway = gateway or ModelGateway()
    effective_jd = effective_position_jd(position)
    result = _generate_rule_result(position, effective_jd, selected_gateway)
    if should_cancel and should_cancel():
        raise RuleGenerationCancelled("岗位规则草稿生成已取消。")
    payload = validate_rule_payload(result["payload"])
    payload["evaluation_jd"] = effective_jd
    if should_cancel and should_cancel():
        raise RuleGenerationCancelled("岗位规则草稿生成已取消。")
    latest = position.rule_versions.aggregate(value=Max("version"))["value"] or 0
    decision = position.jd_decisions.filter(is_current=True).first()
    rule = PositionRuleVersion.objects.create(
        position=position,
        version=latest + 1,
        jd_decision=decision,
        source_jd_snapshot=effective_jd,
        created_by=actor,
        **payload,
    )
    _record_rule_usage(rule, actor, result)
    return rule


def create_initial_published_rule(position, actor, gateway=None, should_cancel=None):
    if should_cancel and should_cancel():
        raise RuleGenerationCancelled("岗位初始规则生成已取消。")
    existing = position.rule_versions.order_by("-version").first()
    if existing:
        return existing, False
    effective_jd = (position.evaluation_jd or position.source_jd or "").strip()
    if not effective_jd:
        raise RuleDraftError("北森岗位说明为空，无法自动生成初始规则 V0。")

    result = _generate_rule_result(position, effective_jd, gateway)
    if should_cancel and should_cancel():
        raise RuleGenerationCancelled("岗位初始规则生成已取消。")
    payload = validate_rule_payload(result["payload"])
    payload["evaluation_jd"] = effective_jd

    with transaction.atomic():
        if should_cancel and should_cancel():
            raise RuleGenerationCancelled("岗位初始规则生成已取消。")
        locked_position = type(position).objects.select_for_update().get(pk=position.pk)
        existing = locked_position.rule_versions.order_by("-version").first()
        if existing:
            return existing, False
        decision = locked_position.jd_decisions.filter(is_current=True).first()
        if not decision:
            decision = confirm_jd(
                locked_position,
                PositionJdDecision.DecisionType.BEISEN,
                actor,
            )
        rule = PositionRuleVersion.objects.create(
            position=locked_position,
            version=0,
            jd_decision=decision,
            source_jd_snapshot=effective_jd,
            created_by=actor,
            **payload,
        )
        rule.publish(actor)
        record_audit(
            actor,
            "position_rule.auto_publish_v0",
            rule,
            {"position_id": locked_position.pk, "jd_decision_id": decision.pk},
        )
        _record_rule_usage(rule, actor, result)
    return rule, True


def jd_diff(current, source):
    return "\n".join(
        difflib.unified_diff(
            (current or "").splitlines(),
            (source or "").splitlines(),
            fromfile="当前系统评估 JD",
            tofile="北森最新 JD",
            lineterm="",
        )
    )


@transaction.atomic
def delete_rule_version(rule, actor, force=False):
    pos = rule.position
    version_num = rule.version
    item_count = rule.analysis_items.count()
    is_published = rule.status == PositionRuleVersion.Status.PUBLISHED

    if is_published:
        raise ValueError("当前正在生效（已发布）的岗位规则不可直接删除。如需删除，请先发布其他规则版本。")

    is_admin = bool(
        getattr(actor, "is_staff", False) or getattr(actor, "is_superuser", False)
    )

    if item_count > 0 and not is_admin:
        raise ValueError(
            f"该规则版本已有 {item_count} 条候选人评估记录关联，为保证招聘数据溯源，无法直接删除。如需清理，请联系系统管理员。"
        )

    if item_count > 0 and is_admin and not force:
        raise ValueError(
            f"REQUIRED_FORCE_CONFIRM:该规则版本已有 {item_count} 条候选人评估报告关联！强行删除将解除历史报告与该规则版本的绑定。确定强行删除吗？"
        )

    if is_admin and force and item_count > 0:
        rule.analysis_items.all().update(rule_version=None)
        record_audit(
            actor,
            "position_rule.force_delete",
            pos,
            {
                "position_id": pos.pk,
                "version": version_num,
                "item_count": item_count,
            },
        )
    else:
        record_audit(
            actor,
            "position_rule.delete",
            pos,
            {"position_id": pos.pk, "version": version_num},
        )

    rule.delete()
    return True

