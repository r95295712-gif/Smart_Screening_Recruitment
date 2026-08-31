import difflib
import hashlib
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from analysis.models import PositionRuleVersion
from recruitment.models import (
    Position,
    PositionConfiguration,
    PositionJdDecision,
)
from recruitment.services.common import record_audit


def text_hash(value):
    return hashlib.sha256((value or "").strip().encode("utf-8")).hexdigest()


def build_text_diff(beisen_jd, document_jd):
    return "\n".join(
        difflib.unified_diff(
            (beisen_jd or "").splitlines(),
            (document_jd or "").splitlines(),
            fromfile="北森岗位说明",
            tofile="参考资料岗位说明",
            lineterm="",
        )
    )


def build_merged_jd(beisen_jd, document_jd):
    import re

    b_text = (beisen_jd or "").strip()
    d_text = (document_jd or "").strip()
    if not d_text:
        return b_text
    if not b_text:
        return d_text
    if b_text == d_text:
        return b_text

    def clean_item(line):
        return re.sub(
            r"^[\d一二三四五六七八九十]+[、.\s\-\)]\s*|^[•\-\*\+]\s*", "", line
        ).strip()

    def parse_sections(text):
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        sections = {"responsibilities": [], "requirements": [], "others": []}
        curr = "responsibilities"
        for l in lines:
            normalized = (
                l.replace(" ", "")
                .replace("【", "")
                .replace("】", "")
                .replace(":", "")
                .replace("：", "")
            )
            if any(
                k in normalized
                for k in ["岗位职责", "工作职责", "主要职责", "职责描述", "职责"]
            ):
                curr = "responsibilities"
                continue
            elif any(
                k in normalized
                for k in ["任职要求", "任职资格", "岗位要求", "职位要求", "招聘要求", "任职条件"]
            ):
                curr = "requirements"
                continue
            elif any(
                k in normalized
                for k in ["加分项", "优先条件", "福利待遇", "其他说明", "备注"]
            ):
                curr = "others"
                continue
            sections[curr].append(l)
        return sections

    sec_b = parse_sections(b_text)
    sec_d = parse_sections(d_text)

    merged_parts = []

    # 1. Responsibilities
    resp_items = []
    seen_resp = set()
    for item in sec_b["responsibilities"] + sec_d["responsibilities"]:
        cleaned = clean_item(item)
        if cleaned and cleaned not in seen_resp:
            seen_resp.add(cleaned)
            resp_items.append(cleaned)

    if resp_items:
        merged_parts.append("岗位职责：")
        for i, item in enumerate(resp_items, 1):
            merged_parts.append(f"{i}. {item}")

    # 2. Requirements
    req_items = []
    seen_req = set()
    for item in sec_b["requirements"] + sec_d["requirements"]:
        cleaned = clean_item(item)
        if cleaned and cleaned not in seen_req:
            seen_req.add(cleaned)
            req_items.append(cleaned)

    if req_items:
        if merged_parts:
            merged_parts.append("")
        merged_parts.append("任职要求：")
        for i, item in enumerate(req_items, 1):
            merged_parts.append(f"{i}. {item}")

    # 3. Others
    other_items = []
    seen_other = set()
    for item in sec_b["others"] + sec_d["others"]:
        cleaned = clean_item(item)
        if cleaned and cleaned not in seen_other:
            seen_other.add(cleaned)
            other_items.append(cleaned)

    if other_items:
        if merged_parts:
            merged_parts.append("")
        merged_parts.append("加分与其它说明：")
        for i, item in enumerate(other_items, 1):
            merged_parts.append(f"{i}. {item}")

    if not merged_parts:
        return f"【岗位职责与要求（合并）】\n{b_text}\n\n【参考补充内容】\n{d_text}"

    return "\n".join(merged_parts)


def ensure_position_configuration(position):
    configuration, _ = PositionConfiguration.objects.get_or_create(position=position)
    return configuration


@dataclass
class ConfigurationState:
    code: str
    label: str
    blockers: list
    can_run: bool
    can_analyze: bool = False
    can_review: bool = False
    current_decision: object = None
    published_rule: object = None
    reviewer_count: int = 0


STATE_LABELS = {
    "pending_match": "待确认匹配",
    "pending_jd": "待确认岗位说明",
    "pending_rule": "待发布评估规则",
    "pending_reviewer": "可分析，待配置负责人",
    "ready": "可用",
    "update_required": "需更新",
    "historical": "历史岗位",
}


def configuration_state(position, update_ready_at=True):
    if position.status == Position.Status.HISTORICAL:
        return ConfigurationState(
            "historical",
            STATE_LABELS["historical"],
            ["历史岗位不能发起新的分析或审核"],
            False,
            False,
            False,
        )

    try:
        configuration = position.configuration
    except PositionConfiguration.DoesNotExist:
        return ConfigurationState(
            "pending_jd",
            STATE_LABELS["pending_jd"],
            ["确认岗位说明"],
            False,
            False,
            False,
        )

    current_decision = position.jd_decisions.filter(is_current=True).first()
    if not current_decision:
        return ConfigurationState(
            "pending_jd",
            STATE_LABELS["pending_jd"],
            ["确认岗位说明"],
            False,
            False,
            False,
        )

    published_rule = (
        position.rule_versions.filter(status=PositionRuleVersion.Status.PUBLISHED)
        .order_by("-version")
        .first()
    )
    if not published_rule:
        return ConfigurationState(
            "pending_rule",
            STATE_LABELS["pending_rule"],
            ["发布岗位评估规则"],
            False,
            False,
            False,
            current_decision=current_decision,
        )

    reviewer_count = position.reviewer_links.filter(reviewer__is_active=True).count()
    if not reviewer_count:
        return ConfigurationState(
            "pending_reviewer",
            STATE_LABELS["pending_reviewer"],
            ["配置审核负责人后可送审"],
            False,
            True,
            False,
            current_decision=current_decision,
            published_rule=published_rule,
        )

    source_changed = current_decision.source_jd_hash != text_hash(position.source_jd)
    rule_outdated = published_rule.jd_decision_id != current_decision.pk
    code = "update_required" if source_changed or rule_outdated else "ready"
    if update_ready_at and not configuration.ready_at:
        configuration.ready_at = timezone.now()
        configuration.save(update_fields=["ready_at", "updated_at"])
    return ConfigurationState(
        code,
        STATE_LABELS[code],
        [],
        True,
        True,
        True,
        current_decision=current_decision,
        published_rule=published_rule,
        reviewer_count=reviewer_count,
    )


def require_analysis_configuration(position):
    try:
        position.configuration
    except PositionConfiguration.DoesNotExist:
        return None
    state = configuration_state(position)
    if not state.can_analyze:
        raise ValueError("；".join(state.blockers))
    return state


def _sync_active_rule_for_jd(position, decision, actor):
    if not decision:
        return
    rule = (
        decision.rule_versions.filter(
            status__in=[
                PositionRuleVersion.Status.PUBLISHED,
                PositionRuleVersion.Status.ARCHIVED,
            ]
        )
        .order_by("-version")
        .first()
    )
    if rule:
        PositionRuleVersion.objects.filter(
            position=position, status=PositionRuleVersion.Status.PUBLISHED
        ).exclude(pk=rule.pk).update(status=PositionRuleVersion.Status.ARCHIVED)
        rule.status = PositionRuleVersion.Status.PUBLISHED
        rule.published_by = actor
        rule.published_at = timezone.now()
        rule.save(update_fields=["status", "published_by", "published_at"])
    else:
        PositionRuleVersion.objects.filter(
            position=position, status=PositionRuleVersion.Status.PUBLISHED
        ).exclude(jd_decision=decision).update(status=PositionRuleVersion.Status.ARCHIVED)


def require_review_configuration(position):
    try:
        position.configuration
    except PositionConfiguration.DoesNotExist:
        return None
    state = configuration_state(position)
    if not state.can_review:
        raise ValueError("；".join(state.blockers))
    return state


def require_runnable_configuration(position):
    return require_review_configuration(position)


@transaction.atomic
def confirm_jd(
    position,
    decision_type,
    actor,
    confirmed_jd="",
    ai_diff_summary="",
    ai_model_identifier="",
):
    configuration = ensure_position_configuration(position)
    document_position = configuration.document_position
    beisen_jd = (position.source_jd or "").strip()
    document_jd = (document_position.jd if document_position else "").strip()
    if decision_type == PositionJdDecision.DecisionType.BEISEN:
        selected_jd = beisen_jd
    elif decision_type == PositionJdDecision.DecisionType.MERGED and not (confirmed_jd or "").strip():
        selected_jd = build_merged_jd(beisen_jd, document_jd)
    else:
        selected_jd = (confirmed_jd or "").strip()
    if not selected_jd:
        raise ValueError("确认后的岗位说明不能为空。")

    source_jd_hash = text_hash(beisen_jd)
    document_jd_hash = text_hash(document_jd)
    current = position.jd_decisions.filter(is_current=True).first()
    if current and (
        current.decision_type == decision_type
        and current.confirmed_jd.strip() == selected_jd
        and current.source_jd_hash == source_jd_hash
        and current.document_jd_hash == document_jd_hash
    ):
        current.was_unchanged = True
        _sync_active_rule_for_jd(position, current, actor)
        record_audit(
            actor,
            "position_jd.confirm_unchanged",
            current,
            {"position_id": position.pk, "version": current.version},
        )
        return current

    # Check if this exact JD decision already exists in history
    existing_match = (
        position.jd_decisions.filter(
            confirmed_jd=selected_jd,
            decision_type=decision_type,
        )
        .order_by("-version")
        .first()
    )
    if existing_match:
        position.jd_decisions.filter(is_current=True).update(is_current=False)
        existing_match.is_current = True
        existing_match.save(update_fields=["is_current"])
        position.evaluation_jd = selected_jd
        position.save(update_fields=["evaluation_jd"])
        _sync_active_rule_for_jd(position, existing_match, actor)
        record_audit(
            actor,
            "position_jd.confirm_existing",
            existing_match,
            {"position_id": position.pk, "version": existing_match.version},
        )
        return existing_match

    position.jd_decisions.filter(is_current=True).update(is_current=False)
    latest = position.jd_decisions.aggregate(value=Max("version"))["value"] or 0
    decision = PositionJdDecision.objects.create(
        position=position,
        version=latest + 1,
        document_position=document_position,
        decision_type=decision_type,
        beisen_jd_snapshot=beisen_jd,
        document_jd_snapshot=document_jd,
        confirmed_jd=selected_jd,
        source_jd_hash=source_jd_hash,
        document_jd_hash=document_jd_hash,
        text_diff=build_text_diff(beisen_jd, document_jd),
        ai_diff_summary=ai_diff_summary,
        ai_model_identifier=ai_model_identifier,
        confirmed_by=actor,
    )
    position.evaluation_jd = selected_jd
    position.save(update_fields=["evaluation_jd"])
    _sync_active_rule_for_jd(position, decision, actor)
    record_audit(
        actor,
        "position_jd.confirm",
        decision,
        {
            "position_id": position.pk,
            "decision_type": decision_type,
            "version": decision.version,
        },
    )
    return decision


@transaction.atomic
def delete_jd_decision(decision, actor, force=False):
    if decision.is_current:
        raise ValueError("当前正在生效的岗位说明版本不可直接删除。如需删除，请先切换或确认其他版本为当前生效。")

    rule_count = decision.rule_versions.count()
    has_analysis_records = any(
        rule.analysis_items.exists() for rule in decision.rule_versions.all()
    )

    is_admin = bool(
        getattr(actor, "is_staff", False) or getattr(actor, "is_superuser", False)
    )

    if (rule_count > 0 or has_analysis_records) and not is_admin:
        raise ValueError(
            "该岗位说明版本已有规则或历史评估记录关联，无法直接删除。如需清理，请联系系统管理员。"
        )

    if (rule_count > 0 or has_analysis_records) and is_admin and not force:
        raise ValueError(
            f"REQUIRED_FORCE_CONFIRM:该岗位说明版本关联了 {rule_count} 个规则版本及历史评估记录！强行删除将解除这些规则与该版本的绑定。确定强行删除吗？"
        )

    version_num = decision.version
    pos = decision.position

    if is_admin and force:
        decision.rule_versions.all().update(jd_decision=None)
        record_audit(
            actor,
            "position_jd.force_delete",
            pos,
            {
                "position_id": pos.pk,
                "version": version_num,
                "rule_count": rule_count,
            },
        )
    else:
        record_audit(
            actor,
            "position_jd.delete",
            pos,
            {"position_id": pos.pk, "version": version_num},
        )

    decision.delete()
    return True

