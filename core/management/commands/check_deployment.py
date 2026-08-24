import os
import sys
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import get_connection
from django.core.management.base import BaseCommand
from django.db import connection

from accounts.models import User


class Command(BaseCommand):
    help = "检查生产/部署环境的基础设施连通性与配置项，提前排除上线问题。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-external",
            action="store_true",
            help="跳过外部网络接口（如北森 OpenAPI、大模型网关、SMTP）的连通性测试",
        )

    def handle(self, *args, **options):
        skip_external = options["skip_external"]
        self.stdout.write(self.style.MIGRATE_HEADING("=== 智筛招聘 部署环境预检 ==="))

        results = []

        # 1. 基础配置与安全检查
        results.append(self._check_settings())

        # 2. 数据库连通性
        results.append(self._check_database())

        # 3. Redis / 消息队列
        results.append(self._check_redis())

        # 4. 对象存储 / 本地存储
        results.append(self._check_storage())

        # 5. 外部接口测试（可选）
        if not skip_external:
            results.append(self._check_model_api())
            results.append(self._check_italent_api())
            results.append(self._check_smtp())

        # 总结
        self.stdout.write("\n" + self.style.MIGRATE_HEADING("=== 检查结果汇总 ==="))
        failed_count = sum(1 for status, _ in results if status == "FAIL")
        warn_count = sum(1 for status, _ in results if status == "WARN")
        ok_count = sum(1 for status, _ in results if status == "OK")

        self.stdout.write(
            f"通过: {self.style.SUCCESS(str(ok_count))} 项 | "
            f"警告: {self.style.WARNING(str(warn_count))} 项 | "
            f"失败: {self.style.ERROR(str(failed_count))} 项"
        )

        if failed_count > 0:
            self.stdout.write(
                self.style.ERROR("\n[!] 存在关键项未通过，请检查上述错误并修改配置后再行上线。")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("\n[√] 部署核心检查通过，可以正常启动服务。")
            )

    def _check_settings(self):
        self.stdout.write("\n[1/7] 检查 Django 核心配置...")
        issues = []
        settings_mod = str(getattr(settings, "SETTINGS_MODULE", "") or os.getenv("DJANGO_SETTINGS_MODULE", ""))
        is_prod = "production" in settings_mod

        if settings.SECRET_KEY in {
            "development-only-secret-key",
            "replace-with-a-long-random-value",
        } or len(settings.SECRET_KEY) < 30:
            if is_prod:
                issues.append(("FAIL", "DJANGO_SECRET_KEY 必须设置为至少 50 位的随机强密钥。"))
            else:
                issues.append(("WARN", "DJANGO_SECRET_KEY 处于开发默认值。"))

        if not settings.ALLOWED_HOSTS or settings.ALLOWED_HOSTS == ["*"]:
            if is_prod:
                issues.append(("WARN", "DJANGO_ALLOWED_HOSTS 为空或设为通配符 '*'，建议指定内网 IP 或域名。"))

        if not settings.CSRF_TRUSTED_ORIGINS and is_prod:
            issues.append(
                (
                    "WARN",
                    "DJANGO_CSRF_TRUSTED_ORIGINS 为空。若无网关直连，请配置如 http://<IP>:8000 避免登录报 403。",
                )
            )

        if not issues:
            self.stdout.write(self.style.SUCCESS("  [OK] 基础与安全配置正常。"))
            return "OK", "Settings"
        
        has_fail = any(level == "FAIL" for level, _ in issues)
        for level, msg in issues:
            styled_msg = self.style.ERROR(f"  [FAIL] {msg}") if level == "FAIL" else self.style.WARNING(f"  [WARN] {msg}")
            self.stdout.write(styled_msg)
        return ("FAIL" if has_fail else "WARN"), "Settings"

    def _check_database(self):
        self.stdout.write("\n[2/7] 检查数据库连通性...")
        try:
            connection.ensure_connection()
            user_count = User.objects.count()
            db_engine = connection.vendor
            self.stdout.write(
                self.style.SUCCESS(f"  [OK] 数据库连接成功 ({db_engine})，当前用户数: {user_count}")
            )
            return "OK", "Database"
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  [FAIL] 数据库连接失败: {exc}"))
            return "FAIL", "Database"

    def _check_redis(self):
        self.stdout.write("\n[3/7] 检查 Redis 连通性...")
        try:
            import redis
            redis_client = redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=3)
            redis_client.ping()
            self.stdout.write(
                self.style.SUCCESS(f"  [OK] Redis 连接正常 ({settings.CELERY_BROKER_URL})")
            )
            return "OK", "Redis"
        except Exception as exc:
            self.stdout.write(
                self.style.ERROR(
                    f"  [FAIL] 无法连接 Redis ({settings.CELERY_BROKER_URL}): {exc}\n"
                    "         请确保 Redis 容器已启动且端口正常通信。"
                )
            )
            return "FAIL", "Redis"

    def _check_storage(self):
        self.stdout.write("\n[4/7] 检查存储后端 (Storage)...")
        test_filename = f"healthcheck_{uuid.uuid4().hex[:8]}.txt"
        test_content = b"healthcheck"
        try:
            saved_path = default_storage.save(test_filename, ContentFile(test_content))
            if not default_storage.exists(saved_path):
                raise RuntimeError("写入测试文件后无法检测到存在。")
            read_bytes = default_storage.open(saved_path).read()
            if read_bytes != test_content:
                raise RuntimeError("读取测试文件内容与写入不一致。")
            default_storage.delete(saved_path)

            storage_name = default_storage.__class__.__name__
            self.stdout.write(
                self.style.SUCCESS(f"  [OK] 存储后端读写正常 ({storage_name})")
            )
            return "OK", "Storage"
        except Exception as exc:
            self.stdout.write(
                self.style.ERROR(f"  [FAIL] 存储后端读写失败: {exc}")
            )
            return "FAIL", "Storage"

    def _check_model_api(self):
        self.stdout.write("\n[5/7] 检查 AI 模型网关连通性...")
        if not getattr(settings, "MODEL_API_KEY", ""):
            self.stdout.write(
                self.style.WARNING("  [WARN] 未配置 MODEL_API_KEY，将无法使用 AI 简历分析与规则自动生成。")
            )
            return "WARN", "ModelAPI"

        try:
            from openai import OpenAI
            timeout = getattr(settings, "MODEL_REQUEST_TIMEOUT", 30) or 30
            client = OpenAI(
                api_key=settings.MODEL_API_KEY,
                base_url=settings.MODEL_BASE_URL or None,
                timeout=timeout,
                max_retries=1,
            )
            response = client.chat.completions.create(
                model=settings.MODEL_NAME,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"  [OK] AI 模型网关通信正常 (Model: {settings.MODEL_NAME})"
                )
            )
            return "OK", "ModelAPI"
        except Exception as exc:
            self.stdout.write(
                self.style.ERROR(f"  [FAIL] AI 模型网关调用异常: {exc}")
            )
            return "FAIL", "ModelAPI"

    def _check_italent_api(self):
        self.stdout.write("\n[6/7] 检查北森 OpenAPI 授权...")
        if not getattr(settings, "ITALENT_APP_KEY", "") or not getattr(settings, "ITALENT_APP_SECRET", ""):
            self.stdout.write(
                self.style.WARNING("  [WARN] 未配置 ITALENT_APP_KEY / ITALENT_APP_SECRET，北森同步将使用假数据或不可用。")
            )
            return "WARN", "iTalentAPI"

        try:
            from recruitment.integrations.italent import ITalentClient
            client = ITalentClient()
            token = client.get_token()
            if token:
                self.stdout.write(
                    self.style.SUCCESS("  [OK] 北森 OpenAPI Token 校验成功。")
                )
                return "OK", "iTalentAPI"
            raise RuntimeError("未获取到有效 Token。")
        except Exception as exc:
            self.stdout.write(
                self.style.ERROR(f"  [FAIL] 北森 OpenAPI Token 获取失败: {exc}")
            )
            return "FAIL", "iTalentAPI"

    def _check_smtp(self):
        self.stdout.write("\n[7/7] 检查 SMTP 邮件服务...")
        if not getattr(settings, "EMAIL_HOST", ""):
            self.stdout.write(
                self.style.WARNING("  [WARN] 未配置 EMAIL_HOST，负责人邮件推送将无法实际发送。")
            )
            return "WARN", "SMTP"

        try:
            connection = get_connection(timeout=5)
            connection.open()
            connection.close()
            self.stdout.write(
                self.style.SUCCESS(
                    f"  [OK] SMTP 服务器连接正常 ({settings.EMAIL_HOST}:{settings.EMAIL_PORT})"
                )
            )
            return "OK", "SMTP"
        except Exception as exc:
            self.stdout.write(
                self.style.ERROR(f"  [FAIL] SMTP 服务器连接失败: {exc}")
            )
            return "FAIL", "SMTP"
