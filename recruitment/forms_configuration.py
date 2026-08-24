from django import forms

from recruitment.models import (
    DocumentPosition,
    PositionJdDecision,
    ReferenceDocument,
)


class ReferenceDocumentUploadForm(forms.Form):
    document_type = forms.ChoiceField(
        choices=ReferenceDocument.DocumentType.choices,
        label="资料类型",
    )
    file = forms.FileField(label="选择文件")

    def clean(self):
        cleaned = super().clean()
        uploaded_file = cleaned.get("file")
        document_type = cleaned.get("document_type")
        if not uploaded_file or not document_type:
            return cleaned
        suffix = uploaded_file.name.lower().rsplit(".", 1)[-1]
        expected = {
            ReferenceDocument.DocumentType.JOB_SUMMARY_DOCX: "docx",
            ReferenceDocument.DocumentType.REVIEWER_MAPPING_XLSX: "xlsx",
        }[document_type]
        if suffix != expected:
            raise forms.ValidationError(f"该资料请选择 {expected.upper()} 文件。")
        if uploaded_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError("单个参考资料不能超过 10MB。")
        return cleaned


class PositionMatchForm(forms.Form):
    document_position = forms.ModelChoiceField(
        queryset=DocumentPosition.objects.none(),
        required=False,
        label="参考资料中的岗位",
        help_text="下拉选项来自当前已发布的招聘汇总参考资料。",
    )
    no_match = forms.BooleanField(required=False, label="确认没有对应参考岗位")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document_position"].queryset = DocumentPosition.objects.filter(
            is_active=True,
            reference_document__document_type=ReferenceDocument.DocumentType.JOB_SUMMARY_DOCX,
            reference_document__status=ReferenceDocument.Status.ACTIVE,
        )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("document_position") and not cleaned.get("no_match"):
            raise forms.ValidationError("请选择参考岗位，或确认没有对应参考岗位。")
        return cleaned


class JdDecisionForm(forms.Form):
    decision_type = forms.ChoiceField(
        choices=PositionJdDecision.DecisionType.choices,
        label="采用方式",
    )
    confirmed_jd = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 16}),
        label="最终岗位说明",
        help_text="这里编辑并确认的是岗位说明；候选人评估依据在下一步“评估依据与规则”中单独配置。",
    )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("decision_type")
            != PositionJdDecision.DecisionType.BEISEN
            and not (cleaned.get("confirmed_jd") or "").strip()
        ):
            raise forms.ValidationError("人工调整或合并时，请填写确认后的岗位说明。")
        return cleaned


class ReviewerForm(forms.Form):
    name = forms.CharField(max_length=255, label="负责人姓名")
    email = forms.EmailField(label="负责人邮箱")
