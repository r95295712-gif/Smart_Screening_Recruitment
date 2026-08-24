from django.contrib import admin

from .models import (
    Application,
    AuditEvent,
    Candidate,
    ExclusionMarker,
    Notification,
    Position,
    ResumeVersion,
    SyncJob,
)

admin.site.register(
    [Position, Candidate, Application, ResumeVersion, SyncJob, ExclusionMarker, AuditEvent, Notification]
)
