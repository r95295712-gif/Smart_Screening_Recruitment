from django.urls import reverse

from recruitment.models import AuditEvent, Notification


def record_audit(actor, action, instance, metadata=None):
    if hasattr(instance, "_meta"):
        object_type = instance._meta.label
        object_reference = str(getattr(instance, "pk", ""))
    elif isinstance(instance, (list, tuple)) and len(instance) == 2:
        object_type = str(instance[0])
        object_reference = str(instance[1])
    else:
        object_type = str(instance or "")
        object_reference = ""
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=object_type,
        object_reference=object_reference,
        metadata=metadata or {},
    )


def notify(user, title, message="", notification_type=Notification.Type.INFO, target_url=""):
    return Notification.objects.create(
        user=user,
        type=notification_type,
        title=title,
        message=message,
        target_url=target_url,
    )


def notify_admins(title, message="", notification_type=Notification.Type.INFO):
    from accounts.models import User

    for user in User.objects.filter(role=User.Role.ADMIN, is_active=True):
        notify(user, title, message, notification_type)
