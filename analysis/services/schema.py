class ReportValidationError(ValueError):
    pass


LIST_FIELDS = [
    "hard_requirement_results",
    "dimension_results",
    "strengths",
    "risks",
    "missing_information",
    "interview_focus",
    "interview_questions",
]


def rating_for_score(score, thresholds):
    priority = int((thresholds or {}).get("priority", 80))
    review = int((thresholds or {}).get("review", 60))
    if score >= priority:
        return "priority"
    if score >= review:
        return "review"
    return "low"


def validate_report_payload(payload, thresholds=None):
    if not isinstance(payload, dict):
        raise ReportValidationError("模型报告不是 JSON 对象。")
    try:
        score = int(payload["score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReportValidationError("模型报告缺少有效 score。") from exc
    if score < 0 or score > 100:
        raise ReportValidationError("模型评分必须在 0 到 100 之间。")
    normalized = dict(payload)
    normalized["score"] = score
    normalized["rating"] = rating_for_score(score, thresholds)
    for field in LIST_FIELDS:
        value = normalized.get(field, [])
        if not isinstance(value, list):
            raise ReportValidationError(f"{field} 必须是数组。")
        normalized[field] = value
    return normalized

