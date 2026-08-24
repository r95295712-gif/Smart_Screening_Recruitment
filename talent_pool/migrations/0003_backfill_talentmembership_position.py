from django.db import migrations


def backfill_talent_positions(apps, schema_editor):
    TalentMembership = apps.get_model("talent_pool", "TalentMembership")
    Application = apps.get_model("recruitment", "Application")
    for membership in TalentMembership.objects.filter(position__isnull=True):
        latest_app = (
            Application.objects.filter(
                candidate_id=membership.candidate_id, deleted_at__isnull=True
            )
            .order_by("-applied_at", "-created_at")
            .first()
        )
        if latest_app and latest_app.position_id:
            membership.position_id = latest_app.position_id
            membership.save(update_fields=["position"])


class Migration(migrations.Migration):
    dependencies = [
        ("talent_pool", "0002_talentmembership_position"),
        ("recruitment", "0003_sync_job_cancellation_statuses"),
    ]

    operations = [
        migrations.RunPython(backfill_talent_positions, reverse_code=migrations.RunPython.noop),
    ]
