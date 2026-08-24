import django.db.models.deletion
import recruitment.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ReferenceDocument",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "document_type",
                    models.CharField(
                        choices=[
                            ("job_summary_docx", "招聘汇总文档"),
                            ("reviewer_mapping_xlsx", "岗位负责人表"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "file",
                    models.FileField(
                        blank=True,
                        upload_to=recruitment.models.reference_document_upload_path,
                    ),
                ),
                ("content_hash", models.CharField(db_index=True, max_length=64)),
                ("version", models.PositiveIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "待发布"),
                            ("active", "当前有效"),
                            ("archived", "历史版本"),
                            ("parse_failed", "解析失败"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("parse_error", models.TextField(blank=True)),
                (
                    "published_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="published_reference_documents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="uploaded_reference_documents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["document_type", "-version"]},
        ),
        migrations.CreateModel(
            name="DocumentPosition",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("normalized_title", models.CharField(db_index=True, max_length=255)),
                ("aliases", models.JSONField(blank=True, default=list)),
                ("jd", models.TextField(blank=True)),
                ("source_section", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "reference_document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="positions",
                        to="recruitment.referencedocument",
                    ),
                ),
            ],
            options={"ordering": ["title"]},
        ),
        migrations.CreateModel(
            name="PositionConfiguration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "match_status",
                    models.CharField(
                        choices=[
                            ("pending", "待匹配"),
                            ("suggested", "待确认"),
                            ("confirmed", "已确认"),
                            ("no_match", "确认无匹配"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("match_method", models.CharField(blank=True, max_length=64)),
                (
                    "match_score",
                    models.DecimalField(decimal_places=4, default=0, max_digits=5),
                ),
                ("matched_at", models.DateTimeField(blank=True, null=True)),
                ("ready_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "document_position",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="position_configurations",
                        to="recruitment.documentposition",
                    ),
                ),
                (
                    "matched_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="matched_position_configurations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "position",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="configuration",
                        to="recruitment.position",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PositionJdDecision",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("version", models.PositiveIntegerField()),
                (
                    "decision_type",
                    models.CharField(
                        choices=[
                            ("beisen", "采用北森"),
                            ("manual", "人工调整"),
                            ("merged", "合并 JD"),
                        ],
                        max_length=16,
                    ),
                ),
                ("beisen_jd_snapshot", models.TextField(blank=True)),
                ("document_jd_snapshot", models.TextField(blank=True)),
                ("confirmed_jd", models.TextField()),
                ("source_jd_hash", models.CharField(blank=True, max_length=64)),
                ("document_jd_hash", models.CharField(blank=True, max_length=64)),
                ("text_diff", models.TextField(blank=True)),
                ("ai_diff_summary", models.TextField(blank=True)),
                ("ai_model_identifier", models.CharField(blank=True, max_length=255)),
                ("is_current", models.BooleanField(default=True)),
                ("confirmed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "confirmed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="confirmed_position_jds",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document_position",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="jd_decisions",
                        to="recruitment.documentposition",
                    ),
                ),
                (
                    "position",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="jd_decisions",
                        to="recruitment.position",
                    ),
                ),
            ],
            options={
                "ordering": ["position", "-version"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("position", "version"),
                        name="unique_position_jd_decision_version",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("is_current", True)),
                        fields=("position",),
                        name="unique_current_position_jd_decision",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="referencedocument",
            constraint=models.UniqueConstraint(
                fields=("document_type", "version"),
                name="unique_reference_document_version",
            ),
        ),
    ]
