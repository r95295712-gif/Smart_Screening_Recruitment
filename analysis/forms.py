from django import forms

from .models import PositionRuleVersion, ReportNote


class PositionRuleForm(forms.ModelForm):
    priority_threshold = forms.IntegerField(
        min_value=0,
        max_value=100,
        label="优先推荐起始分",
    )
    review_threshold = forms.IntegerField(
        min_value=0,
        max_value=100,
        label="建议复核起始分",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["evaluation_jd"].disabled = True

        for field_name in ("hard_requirements", "dimensions", "bonus_items"):
            self.fields[field_name].widget = forms.HiddenInput()
        thresholds = self.instance.rating_thresholds or {}
        if not self.is_bound:
            self.initial["priority_threshold"] = thresholds.get("priority", 80)
            self.initial["review_threshold"] = thresholds.get("review", 60)

    def _clean_rule_items(self, field_name, item_label, include_weight=False):
        value = self.cleaned_data.get(field_name) or []
        if not isinstance(value, list):
            self.add_error(field_name, f"{item_label}格式无法识别，请刷新页面后重试。")
            return []
        normalized = []
        for index, item in enumerate(value, start=1):
            if not isinstance(item, dict):
                self.add_error(field_name, f"第 {index} 项{item_label}格式无法识别。")
                continue
            name = str(item.get("name", "")).strip()
            description = str(item.get("description", "")).strip()
            if not name and not description:
                continue
            if not name:
                self.add_error(field_name, f"第 {index} 项{item_label}缺少名称。")
                continue
            normalized_item = {"name": name, "description": description}
            if include_weight:
                try:
                    weight = int(item.get("weight", 0))
                except (TypeError, ValueError):
                    self.add_error(field_name, f"第 {index} 项评分权重必须是数字。")
                    continue
                if not 0 <= weight <= 100:
                    self.add_error(field_name, f"第 {index} 项评分权重必须在 0 到 100 之间。")
                    continue
                normalized_item["weight"] = weight
            normalized.append(normalized_item)
        return normalized

    def clean(self):
        cleaned = super().clean()
        hard_requirements = self._clean_rule_items(
            "hard_requirements",
            "硬性要求",
        )
        dimensions = self._clean_rule_items(
            "dimensions",
            "评分维度",
            include_weight=True,
        )
        bonus_items = self._clean_rule_items("bonus_items", "加分项")
        if dimensions and sum(item["weight"] for item in dimensions) != 100:
            self.add_error("dimensions", "所有评分维度的权重合计必须为 100。")
        priority = cleaned.get("priority_threshold")
        review = cleaned.get("review_threshold")
        if priority is not None and review is not None and priority <= review:
            self.add_error(
                "priority_threshold",
                "优先推荐起始分必须高于建议复核起始分。",
            )
        cleaned["hard_requirements"] = hard_requirements
        cleaned["dimensions"] = dimensions
        cleaned["bonus_items"] = bonus_items
        if priority is not None and review is not None:
            cleaned["rating_thresholds"] = {
                "priority": priority,
                "review": review,
            }
        return cleaned

    class Meta:
        model = PositionRuleVersion
        fields = [
            "evaluation_jd",
            "hard_requirements",
            "dimensions",
            "bonus_items",
            "rating_thresholds",
        ]
        widgets = {
            "evaluation_jd": forms.Textarea(attrs={"rows": 12}),
            "rating_thresholds": forms.HiddenInput(),
        }
        labels = {
            "evaluation_jd": "岗位说明快照",
            "hard_requirements": "硬性要求清单",
            "dimensions": "评分维度设置",
            "bonus_items": "加分项清单",
            "rating_thresholds": "推荐分数线",
        }


class ReportNoteForm(forms.ModelForm):
    class Meta:
        model = ReportNote
        fields = ["note_type", "content"]
        widgets = {"content": forms.Textarea(attrs={"rows": 4})}
        labels = {
            "note_type": "备注类型",
            "content": "备注内容",
        }
