from django.contrib import admin

from .models import CandidateNote, TalentMembership, TalentTag, TalentTagAssignment

admin.site.register([TalentMembership, TalentTag, TalentTagAssignment, CandidateNote])
