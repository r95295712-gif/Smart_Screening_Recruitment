import django.db.models.deletion
from django.db import migrations, models


def backfill_review_reports(apps, schema_editor):
    AnalysisItem = apps.get_model("analysis", "AnalysisItem")
    AnalysisReport = apps.get_model("analysis", "AnalysisReport")
    ReviewItem = apps.get_model("reviews", "ReviewItem")

    review_items = ReviewItem.objects.select_related("batch").filter(
        analysis_report__isnull=True
    )
    for review_item in review_items.iterator():
        successful_items = AnalysisItem.objects.filter(
            application_id=review_item.application_id,
            status="success",
            created_at__lte=review_item.batch.created_at,
        ).order_by("-created_at")
        same_resume_items = successful_items.filter(
            resume_version_id=review_item.resume_version_id
        )
        candidates = list(same_resume_items) or list(successful_items)
        for analysis_item in candidates:
            report_id = (
                AnalysisReport.objects.filter(item_id=analysis_item.pk)
                .values_list("pk", flat=True)
                .first()
                or analysis_item.reused_report_id
            )
            if report_id:
                ReviewItem.objects.filter(pk=review_item.pk).update(
                    analysis_report_id=report_id
                )
                break


class Migration(migrations.Migration):

    dependencies = [
        ("analysis", "0001_initial"),
        ("reviews", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="reviewitem",
            name="analysis_report",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="review_items",
                to="analysis.analysisreport",
            ),
        ),
        migrations.RunPython(backfill_review_reports, migrations.RunPython.noop),
    ]
