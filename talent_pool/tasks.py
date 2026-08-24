from celery import shared_task
from django.utils import timezone

from .services import purge_removed_memberships


@shared_task
def purge_removed_memberships_task():
    return purge_removed_memberships(timezone.now())

