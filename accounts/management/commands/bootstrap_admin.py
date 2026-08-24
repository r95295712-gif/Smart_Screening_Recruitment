import os

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "根据环境变量安全创建初始管理员。"

    def handle(self, *args, **options):
        username = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "admin")
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
        email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")
        if not password:
            raise CommandError("缺少 BOOTSTRAP_ADMIN_PASSWORD。")
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "role": User.Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "must_change_password": True,
            },
        )
        if created:
            user.set_password(password)
            user.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"管理员 {username} 已创建。"))
        else:
            self.stdout.write(f"管理员 {username} 已存在，未修改密码。")
