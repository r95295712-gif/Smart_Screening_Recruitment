from celery import shared_task

from recruitment.services.common import notify

from .emails import send_review_email
from .models import ReviewBatch


@shared_task
def send_review_batch(batch_id):
    batch = ReviewBatch.objects.select_related(
        "reviewer", "position", "created_by"
    ).get(pk=batch_id)
    try:
        send_review_email(batch)
        batch.email_status = ReviewBatch.EmailStatus.SENT
        batch.status = ReviewBatch.Status.PENDING
        batch.save(update_fields=["email_status", "status"])
        return True
    except Exception as exc:
        batch.email_status = ReviewBatch.EmailStatus.FAILED
        batch.status = ReviewBatch.Status.EMAIL_FAILED
        batch.email_retry_count += 1
        batch.save(
            update_fields=["email_status", "status", "email_retry_count"]
        )
        notify(
            batch.created_by,
            "负责人审核邮件发送失败",
            f"{batch.reviewer}：{exc}",
            notification_type="error",
            target_url=f"/reviews/{batch.pk}/",
        )
        return False
