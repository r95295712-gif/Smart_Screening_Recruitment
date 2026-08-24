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
    document.setFont("STSong-Light", 16)
    document.drawString(50, 800, "智筛招聘 AI 分析报告")
    document.setFont("STSong-Light", 11)
    lines = [
        f"候选人：{report.item.application.candidate}",
        f"岗位：{report.item.application.position}",
        f"匹配分：{report.score}",
        f"推荐等级：{report.get_rating_display()}",
    ]
    for row in present_hard_requirements(report.hard_requirement_results):
        detail = f"；依据：{row['evidence']}" if row["evidence"] else ""
        note = f"；说明：{row['note']}" if row["note"] else ""
        lines.append(
            f"岗位要求｜{row['title']}：{row['status']}{detail}{note}"
        )
    for row in present_dimensions(report.dimension_results):
        evidence = f"；依据：{row['evidence']}" if row["evidence"] else ""
        assessment = (
            f"；判断：{row['assessment']}" if row["assessment"] else ""
        )
        lines.append(
            f"维度评分｜{row['title']}：{row['score_text']}{evidence}{assessment}"
        )
    list_sections = [
        (
            "优势",
            report.strengths,
            ("item", "name", "strength"),
            ("evidence", "details", "reason", "note"),
        ),
        (
            "风险",
            report.risks,
            ("item", "name", "risk"),
            ("evidence", "details", "reason", "note"),
        ),
        (
            "信息不足",
            report.missing_information,
            ("item", "name", "field"),
            ("details", "evidence", "reason", "note"),
        ),
        (
            "面试关注",
            report.interview_focus,
            ("focus", "item", "name"),
            ("reason", "evidence", "details", "purpose"),
        ),
        (
            "面试问题",
            report.interview_questions,
            ("question", "item", "name"),
            ("purpose", "reason", "evidence", "details"),
        ),
    ]
    for title, values, title_keys, detail_keys in list_sections:
        lines.append(
            f"{title}："
            + "；".join(
                insight_text(value, title_keys, detail_keys)
                for value in values
            )
        )
    y = 770
    for line in lines:
        for start in range(0, len(line), 42):
            document.drawString(50, y, line[start : start + 42])
            y -= 18
            if y < 60:
                document.showPage()
                document.setFont("STSong-Light", 11)
                y = 800
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
