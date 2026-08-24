from django import forms

from .models import Position


class PositionFilterForm(forms.Form):
    q = forms.CharField(required=False, label="搜索")
    status = forms.ChoiceField(
        required=False,
        choices=[("", "全部状态"), *Position.Status.choices],
        label="岗位状态",
    )


class ApplicationFilterForm(forms.Form):
    q = forms.CharField(required=False, label="候选人")
    analysis_status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "全部分析状态"),
            ("unanalysed", "未分析"),
            ("success", "已完成"),
            ("pending", "处理中"),
            ("failed", "失败"),
        ],
        label="AI 状态",
    )
    rating = forms.ChoiceField(
        required=False,
        choices=[
            ("", "全部推荐等级"),
            ("priority", "优先评估"),
            ("review", "建议人工复核"),
            ("low", "匹配度较低"),
        ],
        label="推荐等级",
    )
    review_status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "全部审核状态"),
            ("pending", "待审核"),
            ("completed", "已完成"),
            ("none", "未送审"),
        ],
        label="审核状态",
    )
    talent_status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "全部人才库状态"),
            ("active", "已入库"),
            ("none", "未入库"),
        ],
        label="人才库",
    )
    applied_from = forms.DateField(
        required=False,
        label="投递开始日期",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    applied_to = forms.DateField(
        required=False,
        label="投递结束日期",
        widget=forms.DateInput(attrs={"type": "date"}),
    )


class DeleteApplicationForm(forms.Form):
    reason = forms.CharField(max_length=255, label="删除原因")
