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
        record_audit(
            actor,
            "position_jd.confirm_unchanged",
            current,
            {"position_id": position.pk, "version": current.version},
        )
        return current

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
