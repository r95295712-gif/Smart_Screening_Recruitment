import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from recruitment.models import Application, Position, ResumeVersion


class PromptVersion(models.Model):
    version = models.CharField(max_length=64, unique=True)
    content = models.TextField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.version


class ModelVersion(models.Model):
    provider = models.CharField(max_length=128)
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=128)
    is_active = models.BooleanField(default=False)
    input_cost_per_million = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    output_cost_per_million = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "name", "version"], name="unique_model_version"
            )
        ]

    def __str__(self):
        return f"{self.provider}/{self.name}:{self.version}"


class PositionRuleVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "草稿"
        PUBLISHED = "published", "已发布"
        ARCHIVED = "archived", "历史"

    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name="rule_versions")
    jd_decision = models.ForeignKey(
        "recruitment.PositionJdDecision",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rule_versions",
    )
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    evaluation_jd = models.TextField(blank=True)
    hard_requirements = models.JSONField(default=list, blank=True)
    dimensions = models.JSONField(default=list, blank=True)
    bonus_items = models.JSONField(default=list, blank=True)
    rating_thresholds = models.JSONField(
        default=dict,
        blank=True,
        help_text="默认包含 priority/review/low 三个区间。",
    )
    source_jd_snapshot = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_position_rules",
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_position_rules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["position", "version"], name="unique_position_rule_version"
            )
        ]

    def publish(self, actor):
        configuration = getattr(self.position, "configuration", None)
        if configuration:
            if self.jd_decision:
                if not self.jd_decision.is_current:
                    self.position.jd_decisions.filter(is_current=True).update(is_current=False)
                    self.jd_decision.is_current = True
                    self.jd_decision.save(update_fields=["is_current"])
                    self.position.evaluation_jd = self.jd_decision.confirmed_jd
                    self.position.save(update_fields=["evaluation_jd"])
            else:
                current_decision = self.position.jd_decisions.filter(is_current=True).first()
                if not current_decision:
                    raise ValidationError("请先确认岗位说明，再发布规则。")
                if (
                    self.evaluation_jd.strip() != current_decision.confirmed_jd.strip()
                    or self.source_jd_snapshot.strip() != current_decision.confirmed_jd.strip()
                ):
                    raise ValidationError("规则所用岗位说明与当前确认内容不一致，请重新生成草稿。")
        PositionRuleVersion.objects.filter(
            position=self.position, status=self.Status.PUBLISHED
        ).exclude(pk=self.pk).update(status=self.Status.ARCHIVED)
        self.status = self.Status.PUBLISHED
        self.published_by = actor
        self.published_at = timezone.now()
        self.save(update_fields=["status", "published_by", "published_at"])

    def __str__(self):
        return f"{self.position} · V{self.version}"


class RuleGenerationOperation(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "生成中"
        CANCELLATION_REQUESTED = "cancellation_requested", "正在取消"
        CANCELLED = "cancelled", "已取消"
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        related_name="rule_generation_operations",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rule_generation_operations",
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class PositionRuleInitialization(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "等待生成"
        RUNNING = "running", "生成中"
        SUCCESS = "success", "已完成"
        FAILED = "failed", "生成失败"
        CANCELLATION_REQUESTED = "cancellation_requested", "正在取消"
        CANCELLED = "cancelled", "已取消"

    sync_job = models.ForeignKey(
        "recruitment.SyncJob",
        on_delete=models.CASCADE,
        related_name="rule_initializations",
    )
    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        related_name="rule_initializations",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_rule_initializations",
    )
    rule_version = models.ForeignKey(
        PositionRuleVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="initialization_tasks",
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["sync_job", "position"],
                name="unique_sync_position_rule_initialization",
            )
        ]

    def __str__(self):
        return f"{self.position} · {self.get_status_display()}"


class AnalysisJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "等待"
        RUNNING = "running", "执行中"
        SUCCESS = "success", "成功"
        PARTIAL = "partial", "部分成功"
        FAILED = "failed", "失败"
        CANCELLATION_REQUESTED = "cancellation_requested", "正在取消"
        CANCELLED = "cancelled", "已取消"

    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name="analysis_jobs")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="analysis_jobs"
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PENDING)
    total_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class AnalysisItem(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "等待"
        RUNNING = "running", "分析中"
        SUCCESS = "success", "成功"
        PARSE_FAILED = "parse_failed", "简历解析失败"
        MODEL_ERROR = "model_error", "模型服务异常"
        CANCELLED = "cancelled", "已取消"

    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name="items")
    application = models.ForeignKey(
        Application, on_delete=models.PROTECT, related_name="analysis_items"
    )
    resume_version = models.ForeignKey(
        ResumeVersion, on_delete=models.PROTECT, related_name="analysis_items"
    )
    rule_version = models.ForeignKey(
        PositionRuleVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analysis_items",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    retry_count = models.PositiveSmallIntegerField(default=0)
    force_reanalysis_reason = models.CharField(max_length=255, blank=True)
    reused_report = models.ForeignKey(
        "AnalysisReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reuse_items",
    )
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "application"], name="unique_analysis_job_application"
            )
        ]


class AnalysisReport(models.Model):
    class Rating(models.TextChoices):
        PRIORITY = "priority", "优先评估"
        REVIEW = "review", "建议人工复核"
        LOW = "low", "匹配度较低"

    item = models.OneToOneField(
        AnalysisItem, on_delete=models.CASCADE, related_name="report"
    )
    prompt_version = models.ForeignKey(PromptVersion, on_delete=models.PROTECT)
    model_version = models.ForeignKey(ModelVersion, on_delete=models.PROTECT)
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    rating = models.CharField(max_length=16, choices=Rating.choices)
    hard_requirement_results = models.JSONField(default=list)
    dimension_results = models.JSONField(default=list)
    strengths = models.JSONField(default=list)
    risks = models.JSONField(default=list)
    missing_information = models.JSONField(default=list)
    interview_focus = models.JSONField(default=list)
    interview_questions = models.JSONField(default=list)
    raw_response = models.JSONField(default=dict)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ReportNote(models.Model):
    class NoteType(models.TextChoices):
        COMMENT = "comment", "补充说明"
        CORRECTION = "correction", "纠错备注"
        CONCLUSION = "conclusion", "人工结论"

    report = models.ForeignKey(AnalysisReport, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    note_type = models.CharField(max_length=16, choices=NoteType.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]


class ModelUsage(models.Model):
    class Purpose(models.TextChoices):
        RESUME_ANALYSIS = "resume_analysis", "简历分析"
        RULE_DRAFT = "rule_draft", "规则草稿"
        JD_DIFF = "jd_diff", "岗位说明差异"

    model_version = models.ForeignKey(ModelVersion, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    success = models.BooleanField(default=True)
    purpose = models.CharField(
        max_length=32,
        choices=Purpose.choices,
        default=Purpose.RESUME_ANALYSIS,
    )
    created_at = models.DateTimeField(auto_now_add=True)
