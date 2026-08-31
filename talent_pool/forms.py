from django import forms

from recruitment.models import Position

from .models import CandidateNote, TalentTag


class TalentFilterForm(forms.Form):
    q = forms.CharField(required=False, label="关键词")
    position = forms.ModelChoiceField(
        required=False,
        queryset=Position.objects.none(),
        label="岗位",
        empty_label="全部岗位",
    )
    tag = forms.ModelChoiceField(
        required=False,
        queryset=TalentTag.objects.none(),
        label="团队标签",
        empty_label="全部标签",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["position"].queryset = Position.objects.all()
        self.fields["tag"].queryset = TalentTag.objects.filter(is_active=True)


class TalentTagSearchForm(forms.Form):
    q = forms.CharField(required=False, label="搜索标签")


class TalentTagForm(forms.ModelForm):
    class Meta:
        model = TalentTag
        fields = ["name"]


class CandidateNoteForm(forms.ModelForm):
    class Meta:
        model = CandidateNote
        fields = ["content"]
        labels = {"content": "备注"}
        widgets = {"content": forms.Textarea(attrs={"rows": 4})}


class RecommendationForm(forms.Form):
    position = forms.ModelChoiceField(
        queryset=Position.objects.filter(status=Position.Status.ACTIVE),
        label="推荐岗位",
    )
    stale_confirmed = forms.BooleanField(
        required=False,
        label="我已知晓简历资料可能过期并仍要推荐",
    )


class TalentInterviewFilterForm(forms.Form):
    q = forms.CharField(required=False, label="关键词")
    position = forms.CharField(required=False, label="岗位")
    result = forms.CharField(required=False, label="面试结果")
    interviewer = forms.CharField(required=False, label="面试官")
    channel = forms.CharField(required=False, label="渠道")
    date_from = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}), label="开始日期"
    )
    date_to = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"}), label="结束日期"
    )


class TalentInterviewForm(forms.ModelForm):
    class Meta:
        from .models import TalentInterview

        model = TalentInterview
        fields = [
            "interview_date",
            "interview_time",
            "position_name",
            "first_interviewer",
            "second_interviewer",
            "result",
            "notes",
            "channel",
        ]
        widgets = {
            "interview_date": forms.DateInput(attrs={"type": "date"}),
            "interview_time": forms.TextInput(attrs={"placeholder": "09:30"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

