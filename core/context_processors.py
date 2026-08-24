def navigation_counts(request):
    if not request.user.is_authenticated:
        return {}
    from recruitment.models import Notification

    return {
        "unread_notification_count": Notification.objects.filter(
            user=request.user, read_at__isnull=True
        ).count()
    }
