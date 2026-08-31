from django.contrib import admin

from .models import (
    CandidateNote,
    InterviewResultOption,
    TalentInterview,
    TalentMembership,
    TalentTag,
    TalentTagAssignment,
)

admin.site.register(
    [
        TalentMembership,
        TalentTag,
        TalentTagAssignment,
        CandidateNote,
        TalentInterview,
        InterviewResultOption,
    ]
)

