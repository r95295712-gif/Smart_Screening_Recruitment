from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0004_positionruleinitialization"),
        ("recruitment", "0003_sync_job_cancellation_statuses"),
    ]

    operations = [
        migrations.AlterField(
            model_name="analysisjob",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "等待"),
                    ("running", "执行中"),
                    ("success", "成功"),
                    ("partial", "部分成功"),
                    ("failed", "失败"),
                    ("cancellation_requested", "正在取消"),
                    ("cancelled", "已取消"),
                ],
                default="pending",
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="positionruleinitialization",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "等待生成"),
                    ("running", "生成中"),
                    ("success", "已完成"),
                    ("failed", "生成失败"),
                    ("cancellation_requested", "正在取消"),
                    ("cancelled", "已取消"),
                ],
                default="queued",
                max_length=24,
            ),
        ),
    ]
