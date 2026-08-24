from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recruitment", "0002_position_configuration"),
    ]

    operations = [
        migrations.AlterField(
            model_name="syncjob",
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
    ]
