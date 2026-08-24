def _text(value):
    if value in (None, ""):
        return ""
    if isinstance(value, (list, tuple)):
        return "；".join(filter(None, (_text(item) for item in value)))
    if isinstance(value, dict):
        return "；".join(
            f"{key}：{_text(item)}" for key, item in value.items() if _text(item)
        )
    return str(value).strip()


def _first(mapping, *keys, default=""):
    if not isinstance(mapping, dict):
        return _text(mapping) or default
    for key in keys:
        value = _text(mapping.get(key))
        if value:
            return value
    return default


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else round(number, 1)


def _status_class(status):
    if "不满足" in status:
        return "danger"
    if "满足" in status:
        return "success"
    if any(keyword in status for keyword in ("不足", "待确认", "未知", "未确认")):
        return "warning"
    return "neutral"


def present_hard_requirements(values):
    results = []
    for value in values or []:
        status = _first(value, "result", "status", default="待确认")
        results.append(
            {
                "title": _first(
                    value,
                    "name",
                    "requirement",
                    "item",
                    default="未命名要求",
                ),
                "status": status,
                "status_class": _status_class(status),
                "evidence": _first(value, "evidence", "details"),
                "note": _first(value, "note", "assessment", "reason"),
            }
        )
    return results


def present_dimensions(values):
    results = []
    for value in values or []:
        weight = _number(value.get("weight")) if isinstance(value, dict) else None
        score = _number(value.get("score")) if isinstance(value, dict) else None
        if score is not None and weight:
            percent = max(0, min(100, round(score * 100 / weight)))
            score_text = f"{score} / {weight}"
        elif score is not None:
            percent = max(0, min(100, round(score)))
            score_text = str(score)
        else:
            percent = 0
            score_text = "-"
        results.append(
            {
                "title": _first(
                    value,
                    "name",
                    "dimension",
                    "item",
                    default="未命名维度",
                ),
                "weight": weight,
                "score": score,
                "score_text": score_text,
                "percent": percent,
                "evidence": _first(value, "evidence", "details"),
                "assessment": _first(value, "assessment", "note", "reason"),
            }
        )
    return results


def present_insights(values, title_keys, detail_keys):
    results = []
    for value in values or []:
        results.append(
            {
                "title": _first(value, *title_keys, default="未提供"),
                "detail": _first(value, *detail_keys),
            }
        )
    return results


def build_report_presentation(report):
    return {
        "hard_requirements": present_hard_requirements(
            report.hard_requirement_results
        ),
        "dimensions": present_dimensions(report.dimension_results),
        "strengths": present_insights(
            report.strengths,
            ("item", "name", "strength"),
            ("evidence", "details", "reason", "note"),
        ),
        "risks": present_insights(
            report.risks,
            ("item", "name", "risk"),
            ("evidence", "details", "reason", "note"),
        ),
        "missing_information": present_insights(
            report.missing_information,
            ("item", "name", "field"),
            ("details", "evidence", "reason", "note"),
        ),
        "interview_focus": present_insights(
            report.interview_focus,
            ("focus", "topic", "item", "name"),
            ("reason", "evidence", "details", "purpose"),
        ),
        "interview_questions": present_insights(
            report.interview_questions,
            ("question", "item", "name"),
            ("purpose", "reason", "evidence", "details"),
        ),
    }


def insight_text(value, title_keys, detail_keys):
    title = _first(value, *title_keys, default="未提供")
    detail = _first(value, *detail_keys)
    return f"{title}：{detail}" if detail else title
