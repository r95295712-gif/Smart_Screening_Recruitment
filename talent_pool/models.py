from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from recruitment.models import Candidate, Position, ResumeVersion


class TalentMembership(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "已入库"
        STALE = "stale", "资料可能过期"
        REMOVED_PENDING = "removed_pending", "已移出待恢复"
        REMOVED = "removed", "已移出"

    candidate = models.OneToOneField(
        Candidate, on_delete=models.CASCADE, related_name="talent_membership"
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="talent_memberships",
        verbose_name="来源岗位",
    )
    resume_version = models.ForeignKey(
        ResumeVersion,
        on_delete=models.PROTECT,
        related_name="talent_memberships",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    joined_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="joined_talents",
    )
    joined_at = models.DateTimeField(default=timezone.now, db_index=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="removed_talents",
    )
    removed_at = models.DateTimeField(null=True, blank=True)
    purge_after = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-joined_at", "-id"]
        indexes = [
            models.Index(
                fields=["status", "-joined_at", "-id"],
                name="talent_status_joined_idx",
            )
        ]

    def remove(self, actor):
        self.status = self.Status.REMOVED_PENDING
        self.removed_by = actor
        self.removed_at = timezone.now()
        self.purge_after = self.removed_at + timedelta(days=3)
        self.save(
            update_fields=["status", "removed_by", "removed_at", "purge_after"]
        )

    def restore(self):
        stale_before = timezone.now() - timedelta(days=730)
        self.status = (
            self.Status.STALE
            if self.resume_version and self.resume_version.created_at < stale_before
            else self.Status.ACTIVE
        )
        self.removed_by = None
        self.removed_at = None
        self.purge_after = None
        self.save(
            update_fields=["status", "removed_by", "removed_at", "purge_after"]
        )


class TalentTag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TalentTagAssignment(models.Model):
    membership = models.ForeignKey(
        TalentMembership, on_delete=models.CASCADE, related_name="tag_assignments"
    )
    tag = models.ForeignKey(TalentTag, on_delete=models.CASCADE, related_name="assignments")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "tag"], name="unique_talent_tag_assignment"
            )
        ]
        indexes = [
            models.Index(
                fields=["tag", "membership"],
                name="talent_tag_assign_idx",
            )
        ]


class CandidateNote(models.Model):
    class Scope(models.TextChoices):
        GENERAL = "general", "候选人备注"
        TALENT = "talent", "人才库专属备注"

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    scope = models.CharField(max_length=16, choices=Scope.choices, default=Scope.GENERAL)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]


WEEKDAYS_CN = {
    0: "星期一",
    1: "星期二",
    2: "星期三",
    3: "星期四",
    4: "星期五",
    5: "星期六",
    6: "星期日",
}


class InterviewResultOption(models.Model):
    name = models.CharField(max_length=64, unique=True)
    color = models.CharField(max_length=32, default="default")
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name


class TalentInterview(models.Model):
    candidate = models.ForeignKey(
        Candidate, on_delete=models.CASCADE, related_name="interviews"
    )
    membership = models.ForeignKey(
        TalentMembership,
        on_delete=models.CASCADE,
        related_name="interviews",
        null=True,
        blank=True,
    )
    position_name = models.CharField(max_length=255, blank=True, db_index=True)
    interview_date = models.DateField(null=True, blank=True, db_index=True)
    interview_time = models.CharField(max_length=32, blank=True)
    first_interviewer = models.CharField(max_length=128, blank=True, db_index=True)
    second_interviewer = models.CharField(max_length=128, blank=True, db_index=True)
    result = models.CharField(max_length=64, default="未面试", db_index=True)
    notes = models.TextField(blank=True)
    channel = models.CharField(max_length=128, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-interview_date", "-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["-interview_date", "-created_at"],
                name="talent_interview_date_idx",
            ),
        ]

    @property
    def formatted_date_with_weekday(self):
        if not self.interview_date:
            return ""
        weekday_str = WEEKDAYS_CN.get(self.interview_date.weekday(), "")
        return f"{self.interview_date.year}年{self.interview_date.month}月{self.interview_date.day}日 {weekday_str}"

    @property
    def result_color_type(self):
        if self.result == "未面试":
            return "muted"
        if self.result == "录用":
            return "success"
        if self.result == "淘汰":
            return "danger"
        return "warning"

    def __str__(self):
        return f"{self.candidate} · {self.position_name} · {self.result}"

