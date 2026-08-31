from io import BytesIO

from django.http import FileResponse
from openpyxl import Workbook
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from .presentation import (
    insight_text,
    present_dimensions,
    present_hard_requirements,
)


def report_pdf_response(report):
    buffer = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    document = canvas.Canvas(buffer)
    
    # Header
    document.setFont("STSong-Light", 18)
    document.drawString(50, 805, "智筛招聘 · AI 候选人分析评估报告")
    
    document.setLineWidth(1)
    document.setStrokeColorRGB(0.2, 0.35, 0.85)
    document.line(50, 795, 545, 795)
    
    y = 775
    document.setFont("STSong-Light", 11)
    
    def check_page_break(current_y, needed_space=40):
        if current_y < needed_space:
            document.showPage()
            document.setFont("STSong-Light", 11)
            return 800
        return current_y

    def draw_section_title(title, current_y):
        current_y = check_page_break(current_y, 60)
        current_y -= 8
        document.setFillColorRGB(0.15, 0.25, 0.6)
        document.setFont("STSong-Light", 13)
        document.drawString(50, current_y, f"■ {title}")
        current_y -= 4
        document.setStrokeColorRGB(0.85, 0.88, 0.95)
        document.setLineWidth(0.5)
        document.line(50, current_y, 545, current_y)
        document.setFillColorRGB(0, 0, 0)
        document.setFont("STSong-Light", 10)
        current_y -= 16
        return current_y

    def draw_wrapped_text(text, current_y, indent=50, max_chars=40, line_height=16):
        for start in range(0, len(text), max_chars):
            current_y = check_page_break(current_y, 40)
            document.drawString(indent, current_y, text[start : start + max_chars])
            current_y -= line_height
        return current_y

    # Basic Info Block
    cand_name = str(report.item.application.candidate)
    pos_name = str(report.item.application.position)
    document.setFont("STSong-Light", 11)
    document.drawString(50, y, f"候选人姓名：{cand_name}")
    document.drawString(300, y, f"应聘岗位：{pos_name}")
    y -= 20
    document.drawString(50, y, f"综合匹配得分：{report.score} 分")
    document.drawString(300, y, f"推荐等级：{report.get_rating_display()}")
    y -= 20
    rule_ver = f"规则版本：V{report.item.rule_version.version}" if hasattr(report.item, "rule_version") and report.item.rule_version else "规则版本：标准"
    document.drawString(50, y, f"{rule_ver}  |  评估模型：{report.model_version}")
    y -= 24

    # 1. Hard requirements
    hard_reqs = present_hard_requirements(report.hard_requirement_results)
    if hard_reqs:
        y = draw_section_title("01 岗位硬性要求核对", y)
        for row in hard_reqs:
            title_line = f"• {row['title']}：【{row['status']}】"
            y = draw_wrapped_text(title_line, y, indent=55, max_chars=40, line_height=15)
            if row.get("evidence"):
                y = draw_wrapped_text(f"  简历依据：{row['evidence']}", y, indent=65, max_chars=38, line_height=14)
            if row.get("note"):
                y = draw_wrapped_text(f"  分析说明：{row['note']}", y, indent=65, max_chars=38, line_height=14)
            y -= 4

    # 2. Dimensions
    dims = present_dimensions(report.dimension_results)
    if dims:
        y = draw_section_title("02 核心维度评分与分析", y)
        for row in dims:
            weight_text = f"（权重 {row['weight']}）" if row.get("weight") else ""
            y = draw_wrapped_text(f"• {row['title']}{weight_text}：{row['score_text']}", y, indent=55, max_chars=40, line_height=15)
            if row.get("evidence"):
                y = draw_wrapped_text(f"  评分依据：{row['evidence']}", y, indent=65, max_chars=38, line_height=14)
            if row.get("assessment"):
                y = draw_wrapped_text(f"  综合判断：{row['assessment']}", y, indent=65, max_chars=38, line_height=14)
            y -= 4

    # 3. Insights
    insights = [
        ("优势与亮点", report.strengths, ("item", "name", "strength"), ("evidence", "details", "reason", "note")),
        ("风险与不足", report.risks, ("item", "name", "risk"), ("evidence", "details", "reason", "note")),
        ("待补充信息", report.missing_information, ("item", "name", "field"), ("details", "evidence", "reason", "note")),
    ]
    has_insights = any(vals for _, vals, _, _ in insights)
    if has_insights:
        y = draw_section_title("03 综合洞察（优势 / 风险 / 缺失）", y)
        for sec_name, vals, t_keys, d_keys in insights:
            if vals:
                y = draw_wrapped_text(f"【{sec_name}】", y, indent=55, max_chars=40, line_height=15)
                for val in vals:
                    t = insight_text(val, t_keys, d_keys)
                    if t:
                        y = draw_wrapped_text(f"  - {t}", y, indent=65, max_chars=38, line_height=14)
                y -= 3

    # 4. Interview Suggestions
    interview_sections = [
        ("面试核实重点", report.interview_focus, ("focus", "item", "name"), ("reason", "evidence", "details", "purpose")),
        ("面试问题建议", report.interview_questions, ("question", "item", "name"), ("purpose", "reason", "evidence", "details")),
    ]
    if any(vals for _, vals, _, _ in interview_sections):
        y = draw_section_title("04 面试与背景核实建议", y)
        for sec_name, vals, t_keys, d_keys in interview_sections:
            if vals:
                y = draw_wrapped_text(f"【{sec_name}】", y, indent=55, max_chars=40, line_height=15)
                for idx, val in enumerate(vals, 1):
                    t = insight_text(val, t_keys, d_keys)
                    if t:
                        y = draw_wrapped_text(f"  {idx}. {t}", y, indent=65, max_chars=38, line_height=14)
                y -= 3

    document.save()
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"analysis-report-{report.pk}.pdf",
        content_type="application/pdf",
    )


def job_excel_response(job):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "分析结果"
    sheet.append(["候选人", "岗位", "分析状态", "匹配分", "推荐等级", "审核状态"])
    for item in job.items.select_related("application__candidate", "application__position"):
        report = item.reused_report
        if hasattr(item, "report"):
            report = item.report
        review = item.application.review_items.order_by("-id").first()
        sheet.append(
            [
                f"候选人-{item.application.candidate_id}",
                str(item.application.position),
                item.get_status_display(),
                report.score if report else "",
                report.get_rating_display() if report else "",
                review.get_decision_display() if review else "未送审",
            ]
        )
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"analysis-job-{job.pk}.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
