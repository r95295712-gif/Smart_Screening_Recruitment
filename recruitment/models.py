import uuid
from datetime import timedelta

from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


def resume_upload_path(instance, filename):
    return f"resumes/{instance.candidate.applicant_id}/{instance.id}/{filename}"


def reference_document_upload_path(instance, filename):
    return f"position-references/{instance.document_type}/{instance.version}/{filename}"


class Position(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "有效"
        HISTORICAL = "historical", "历史"

    class StatusSource(models.TextChoices):
        BEISEN = "beisen", "北森"
        MANUAL = "manual", "人工"
        UNKNOWN = "unknown", "未知"

    beisen_position_id = models.CharField(max_length=128, blank=True, db_index=True)
    requisition_id = models.CharField(max_length=128, blank=True, db_index=True)
    name = models.CharField(max_length=255)
    position_type = models.CharField(max_length=255, blank=True)
    source_jd = models.TextField(blank=True)
    evaluation_jd = models.TextField(blank=True)
    source_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    status_source = models.CharField(
        max_length=16, choices=StatusSource.choices, default=StatusSource.UNKNOWN
    )
    manual_status_override = models.BooleanField(default=False)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["beisen_position_id"],
                condition=~models.Q(beisen_position_id=""),
                name="unique_nonempty_beisen_position_id",
            )
        ]

    def __str__(self):
        return self.name


class ReferenceDocument(models.Model):
    class DocumentType(models.TextChoices):
        JOB_SUMMARY_DOCX = "job_summary_docx", "招聘汇总文档"
        REVIEWER_MAPPING_XLSX = "reviewer_mapping_xlsx", "岗位负责人表"

    class Status(models.TextChoices):
        DRAFT = "draft", "待发布"
        ACTIVE = "active", "当前有效"
        ARCHIVED = "archived", "历史版本"
        PARSE_FAILED = "parse_failed", "解析失败"

    name = models.CharField(max_length=255)
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    file = models.FileField(upload_to=reference_document_upload_path, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_reference_documents",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="published_reference_documents",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    parse_error = models.TextField(blank=True)

    class Meta:
        ordering = ["document_type", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["document_type", "version"],
                name="unique_reference_document_version",
            )
        ]

    def __str__(self):
        return f"{self.get_document_type_display()} V{self.version}"


class DocumentPosition(models.Model):
    reference_document = models.ForeignKey(
        ReferenceDocument,
        on_delete=models.CASCADE,
        related_name="positions",
    )
    title = models.CharField(max_length=255)
    normalized_title = models.CharField(max_length=255, db_index=True)
    aliases = models.JSONField(default=list, blank=True)
    jd = models.TextField(blank=True)
    source_section = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class PositionConfiguration(models.Model):
    class MatchStatus(models.TextChoices):
        PENDING = "pending", "待匹配"
        SUGGESTED = "suggested", "待确认"
        CONFIRMED = "confirmed", "已确认"
        NO_MATCH = "no_match", "确认无匹配"

    position = models.OneToOneField(
        Position,
        on_delete=models.CASCADE,
        related_name="configuration",
    )
    document_position = models.ForeignKey(
        DocumentPosition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="position_configurations",
    )
    match_status = models.CharField(
        max_length=16,
        choices=MatchStatus.choices,
        default=MatchStatus.PENDING,
    )
    match_method = models.CharField(max_length=64, blank=True)
    match_score = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matched_position_configurations",
    )
    matched_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.position} · {self.get_match_status_display()}"


class PositionJdDecision(models.Model):
    class DecisionType(models.TextChoices):
        BEISEN = "beisen", "采用北森"
        MANUAL = "manual", "人工调整"
        MERGED = "merged", "合并 JD"

    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        related_name="jd_decisions",
    )
    version = models.PositiveIntegerField()
    document_position = models.ForeignKey(
        DocumentPosition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jd_decisions",
    )
    decision_type = models.CharField(max_length=16, choices=DecisionType.choices)
    beisen_jd_snapshot = models.TextField(blank=True)
    document_jd_snapshot = models.TextField(blank=True)
    confirmed_jd = models.TextField()
    source_jd_hash = models.CharField(max_length=64, blank=True)
    document_jd_hash = models.CharField(max_length=64, blank=True)
    text_diff = models.TextField(blank=True)
    ai_diff_summary = models.TextField(blank=True)
    ai_model_identifier = models.CharField(max_length=255, blank=True)
    is_current = models.BooleanField(default=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_position_jds",
    )
    confirmed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["position", "version"],
                name="unique_position_jd_decision_version",
            ),
            models.UniqueConstraint(
                fields=["position"],
                condition=models.Q(is_current=True),
                name="unique_current_position_jd_decision",
            ),
        ]

    def __str__(self):
        return f"{self.position} · JD V{self.version}"


class Candidate(models.Model):
    applicant_id = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=64, blank=True, db_index=True)
    email = models.EmailField(blank=True, db_index=True)
    current_company = models.CharField(max_length=255, blank=True, db_index=True)
    school = models.CharField(max_length=255, blank=True, db_index=True)
    skills_text = models.TextField(blank=True)
    profile = models.JSONField(default=dict, blank=True)
    resume_modules = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "applicant_id"]

    def __str__(self):
        return self.name or self.applicant_id


class ResumeVersion(models.Model):
    class SourceType(models.TextChoices):
        ORIGIN = "origin", "北森原始简历"
        STANDARD = "standard", "北森标准简历"
        MANUAL = "manual", "HR 补充文件"

    class ParseStatus(models.TextChoices):
        PENDING = "pending", "等待解析"
        PARSING = "parsing", "解析中"
        SUCCESS = "success", "解析成功"
        LOW_QUALITY = "low_quality", "质量过低"
        FAILED = "failed", "解析失败"
        UNSUPPORTED = "unsupported", "格式不支持"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        Candidate, on_delete=models.CASCADE, related_name="resume_versions"
    )
    source_type = models.CharField(
        max_length=16, choices=SourceType.choices, default=SourceType.ORIGIN
    )
    original_filename = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=128, blank=True)
    source_file = models.FileField(upload_to=resume_upload_path, blank=True)
    standard_pdf = models.FileField(upload_to=resume_upload_path, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    extracted_text = models.TextField(blank=True)
    parse_status = models.CharField(
        max_length=16, choices=ParseStatus.choices, default=ParseStatus.PENDING
    )
    parse_quality = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    parse_error = models.TextField(blank=True)
    protected = models.BooleanField(default=False)
    source_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "content_hash"], name="unique_candidate_resume_hash"
            )
        ]

    def __str__(self):
        return f"{self.candidate} · {self.created_at:%Y-%m-%d %H:%M}"


class ApplicationQuerySet(models.QuerySet):
    def visible(self):
        return self.filter(deleted_at__isnull=True)


class Application(models.Model):
    class SourceType(models.TextChoices):
        BEISEN = "beisen", "北森投递"
        TALENT = "talent", "人才库推荐"

    local_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    application_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    candidate = models.ForeignKey(
        Candidate, on_delete=models.PROTECT, related_name="applications"
    )
    position = models.ForeignKey(
        Position, on_delete=models.PROTECT, related_name="applications"
    )
    source_type = models.CharField(
        max_length=16, choices=SourceType.choices, default=SourceType.BEISEN
    )
    source_channel = models.CharField(max_length=255, blank=True)
    application_status = models.CharField(max_length=128, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    current_resume = models.ForeignKey(
        ResumeVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_for_applications",
    )
    linked_application = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="linked_recommendations",
    )
    source_payload = models.JSONField(default=dict, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    purge_after = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_applications",
    )
    delete_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ApplicationQuerySet.as_manager()

    class Meta:
        ordering = ["-applied_at", "-created_at"]
        indexes = [
            models.Index(fields=["position", "deleted_at"]),
            models.Index(fields=["candidate", "source_type"]),
        ]

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def soft_delete(self, actor, reason=""):
        self.deleted_at = timezone.now()
        self.purge_after = self.deleted_at + timedelta(days=3)
        self.deleted_by = actor
        self.delete_reason = reason
        self.save(
            update_fields=["deleted_at", "purge_after", "deleted_by", "delete_reason"]
        )

    def restore(self):
        self.deleted_at = None
        self.purge_after = None
        self.deleted_by = None
        self.delete_reason = ""
        self.save(
            update_fields=["deleted_at", "purge_after", "deleted_by", "delete_reason"]
        )

    def __str__(self):
        return f"{self.candidate} → {self.position}"


class SyncJob(models.Model):
    class SyncType(models.TextChoices):
        FULL = "full", "全量"
        INCREMENTAL = "incremental", "增量"
        RECONCILIATION = "reconciliation", "校准"
        MANUAL = "manual", "手动"

    class Status(models.TextChoices):
        PENDING = "pending", "等待"
        RUNNING = "running", "执行中"
        SUCCESS = "success", "成功"
        PARTIAL = "partial", "部分成功"
        FAILED = "failed", "失败"
        CANCELLATION_REQUESTED = "cancellation_requested", "正在取消"
        CANCELLED = "cancelled", "已取消"

    sync_type = models.CharField(max_length=20, choices=SyncType.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    cursor = models.CharField(max_length=255, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    total_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ExclusionMarker(models.Model):
    application_id = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64)
    object_reference = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Notification(models.Model):
    class Type(models.TextChoices):
        INFO = "info", "信息"
        SUCCESS = "success", "成功"
        WARNING = "warning", "警告"
        ERROR = "error", "错误"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.INFO)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    target_url = models.CharField(max_length=500, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
