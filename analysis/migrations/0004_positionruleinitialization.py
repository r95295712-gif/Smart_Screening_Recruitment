import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0003_rule_generation_operation"),
        ("recruitment", "0002_position_configuration"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PositionRuleInitialization",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "等待生成"),
                            ("running", "生成中"),
                            ("success", "已完成"),
                            ("failed", "生成失败"),
                        ],
                        default="queued",
                        max_length=16,
                    ),
                ),
                ("retry_count", models.PositiveSmallIntegerField(default=0)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "position",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rule_initializations",
                        to="recruitment.position",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requested_rule_initializations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "rule_version",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="initialization_tasks",
                        to="analysis.positionruleversion",
                    ),
                ),
                (
                    "sync_job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rule_initializations",
                        to="recruitment.syncjob",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("sync_job", "position"),
                        name="unique_sync_position_rule_initialization",
                    )
                ],
            },
        )
    ]
