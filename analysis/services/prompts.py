import json


DEFAULT_SYSTEM_PROMPT = (
    "你是企业招聘辅助分析工具。你只能根据岗位规则和简历明确提供的信息进行客观判断，"
    "不得猜测年龄、健康、疾病、体能、婚育或其他未提供信息。不得自动淘汰候选人。"
    "评判维度遵循向上兼容原则：达到或超越岗位基准条件（如经验更丰富、学历/资质更高）属于优势达标，"
    "严禁将正常的资质溢出判定为风险与不足；仅在存在人岗层级或薪资期望疑虑时列入面试关注点。"
    "输出必须是 JSON，包含 score、hard_requirement_results、dimension_results、"
    "strengths、risks、missing_information、interview_focus、interview_questions。score 为 0 到 100 的整数。"
)


def build_analysis_prompt(rule, resume_text, stale=False):
    payload = {
        "position": rule.position.name,
        "evaluation_jd": rule.evaluation_jd,
        "hard_requirements": rule.hard_requirements,
        "dimensions": rule.dimensions,
        "bonus_items": rule.bonus_items,
        "rating_thresholds": rule.rating_thresholds,
        "resume": resume_text,
        "resume_may_be_stale": stale,
        "instructions": [
            "每项判断必须引用简历依据；信息不足时明确标记信息不足。",
            "优劣、风险和面试关注点可以为空，但不得编造。",
            "年龄和健康条件仅在岗位规则明确要求且简历明确提供时核对。",
            "资料可能过期时将更新时间核实加入 interview_focus，不自动扣分。",
            "【资质条件向上兼容原则】：岗位要求的年限、学历、职级、证书等条件，除明确标注排他性上限（如仅招应届/实习生）外，默认均为准入基准。候选人达到或超出基准（如经验更丰富、资历更深、学历更高）应判定为满足要求与【优势（strengths）】，严禁将其判定为【风险与不足（risks）】。",
            "【风险与不足分类边界】：仅限收录明确未达到最低门槛、关键技能缺失、频繁异常跳槽等明确负向缺陷。",
            "【资历溢出关注原则】：若候选人资历显著高于岗位基准，可能存在稳定性或薪酬匹配疑问，应归入【面试关注点（interview_focus）】供面试官线下核实，不得作为风险扣分。",
        ],
    }
    return json.dumps(payload, ensure_ascii=False)

