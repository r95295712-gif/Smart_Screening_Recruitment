import uuid

from django.conf import settings
from django.db import models

from recruitment.models import Application, Position, ResumeVersion


class Reviewer(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "email"], name="unique_reviewer_identity")
        ]

    def __str__(self):
        return f"{self.name} <{self.email}>"


class PositionReviewer(models.Model):
    class SourceType(models.TextChoices):
        DOCUMENT = "document", "文档匹配"
        MANUAL = "manual", "人工配置"

    position = models.ForeignKey(
        Position, on_delete=models.CASCADE, related_name="reviewer_links"
    )
    reviewer = models.ForeignKey(
        Reviewer, on_delete=models.CASCADE, related_name="position_links"
    )
    source_type = models.CharField(
        max_length=16,
        choices=SourceType.choices,
        default=SourceType.MANUAL,
    )
    source_document_position = models.ForeignKey(
        "recruitment.DocumentPosition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewer_links",
    )
    configured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="configured_position_reviewers",
    )
    configured_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["position", "reviewer"], name="unique_position_reviewer"
            )
        ]


class ReviewBatch(models.Model):
    class Status(models.TextChoices):
        EMAIL_PENDING = "email_pending", "邮件发送中"
        EMAIL_FAILED = "email_failed", "邮件发送失败"
        PENDING = "pending", "待审核"
        PARTIAL = "partial", "部分完成"
        COMPLETED = "completed", "已完成"
        REVOKED = "revoked", "已撤销"
        EXPIRED = "expired", "已过期"

    class EmailStatus(models.TextChoices):
        PENDING = "pending", "等待"
        SENT = "sent", "已发送"
        FAILED = "failed", "失败"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reviewer = models.ForeignKey(Reviewer, on_delete=models.PROTECT, related_name="batches")
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name="review_batches")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="review_batches"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.EMAIL_PENDING
    )
    email_status = models.CharField(
        max_length=16, choices=EmailStatus.choices, default=EmailStatus.PENDING
    )
    email_retry_count = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ReviewItem(models.Model):
    class Decision(models.TextChoices):
        PENDING = "pending", "未提交"
        APPROVED = "approved", "通过"
        REJECTED = "rejected", "不通过"
        DISCUSS = "discuss", "待讨论"
        WITHDRAWN = "withdrawn", "HR 已撤回"

    batch = models.ForeignKey(ReviewBatch, on_delete=models.CASCADE, related_name="items")
    application = models.ForeignKey(
        Application, on_delete=models.PROTECT, related_name="review_items"
    )
    resume_version = models.ForeignKey(
        ResumeVersion, on_delete=models.PROTECT, related_name="review_items"
    )
    analysis_report = models.ForeignKey(
        "analysis.AnalysisReport",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="review_items",
    )
    decision = models.CharField(
        max_length=16, choices=Decision.choices, default=Decision.PENDING
    )
    comment = models.TextField(blank=True)
    is_draft = models.BooleanField(default=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "application"], name="unique_review_batch_application"
            )
        ]
