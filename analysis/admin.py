from django.contrib import admin

from .models import (
    AnalysisItem,
    AnalysisJob,
    AnalysisReport,
    ModelUsage,
    ModelVersion,
    PositionRuleInitialization,
    PositionRuleVersion,
    PromptVersion,
    ReportNote,
)

admin.site.register(
    [
        PromptVersion,
        ModelVersion,
        PositionRuleInitialization,
        PositionRuleVersion,
        AnalysisJob,
        AnalysisItem,
        AnalysisReport,
        ReportNote,
        ModelUsage,
    ]
)
