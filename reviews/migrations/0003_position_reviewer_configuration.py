import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0002_position_configuration"),
        ("reviews", "0002_reviewitem_analysis_report"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="positionreviewer",
            name="configured_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name="positionreviewer",
            name="configured_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="configured_position_reviewers",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="positionreviewer",
            name="source_document_position",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reviewer_links",
                to="recruitment.documentposition",
            ),
        ),
        migrations.AddField(
            model_name="positionreviewer",
            name="source_type",
            field=models.CharField(
                choices=[("document", "文档匹配"), ("manual", "人工配置")],
                default="manual",
                max_length=16,
            ),
        ),
    ]
