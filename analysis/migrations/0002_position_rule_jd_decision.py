import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0001_initial"),
        ("recruitment", "0002_position_configuration"),
    ]

    operations = [
        migrations.AddField(
            model_name="modelusage",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("resume_analysis", "简历分析"),
                    ("rule_draft", "规则草稿"),
                    ("jd_diff", "岗位说明差异"),
                ],
                default="resume_analysis",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="positionruleversion",
            name="jd_decision",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rule_versions",
                to="recruitment.positionjddecision",
            ),
        ),
    ]
