import json


DEFAULT_SYSTEM_PROMPT = """你是企业招聘辅助分析工具。你只能根据岗位规则和简历明确提供的信息进行判断，不得猜测年龄、健康、疾病、体能、婚育或其他未提供信息。不得自动淘汰候选人。输出必须是 JSON，包含 score、hard_requirement_results、dimension_results、strengths、risks、missing_information、interview_focus、interview_questions。score 为 0 到 100 的整数。"""


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
        ],
    }
    return json.dumps(payload, ensure_ascii=False)

