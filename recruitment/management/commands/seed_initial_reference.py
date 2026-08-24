import hashlib
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from recruitment.models import ReferenceDocument
from recruitment.services.reference_import import (
    create_reference_document,
    publish_reference_document,
)


class Command(BaseCommand):
    help = "将随项目部署的招聘汇总文档导入并发布为初始参考资料。"

    def add_arguments(self, parser):
        parser.add_argument("--actor", help="记录为上传人的用户名")

    def handle(self, *args, **options):
        path = Path(settings.INITIAL_REFERENCE_DOCUMENT_PATH)
        if not path.exists():
            raise CommandError(f"未找到初始招聘汇总文档：{path}")
        actor = None
        if options.get("actor"):
            actor = User.objects.filter(
                username=options["actor"],
                is_active=True,
            ).first()
        actor = (
            actor
            or User.objects.filter(is_active=True, role=User.Role.ADMIN).first()
            or User.objects.filter(is_active=True).first()
        )
        if not actor:
            raise CommandError("请先创建初始管理员，再导入招聘汇总文档。")

        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        existing = ReferenceDocument.objects.filter(
            document_type=ReferenceDocument.DocumentType.JOB_SUMMARY_DOCX,
            content_hash=content_hash,
        ).first()
        if existing and existing.positions.exists():
            if existing.status != ReferenceDocument.Status.ACTIVE:
                publish_reference_document(existing, actor)
            self.stdout.write(
                self.style.SUCCESS(
                    f"初始招聘汇总文档已存在：V{existing.version}，无需重复导入。"
                )
            )
            return
        if existing:
            existing.delete()

        with path.open("rb") as handle:
            reference = create_reference_document(
                File(handle, name=path.name),
                ReferenceDocument.DocumentType.JOB_SUMMARY_DOCX,
                actor,
            )
        if reference.status == ReferenceDocument.Status.PARSE_FAILED:
            raise CommandError(f"初始招聘汇总文档解析失败：{reference.parse_error}")
        publish_reference_document(reference, actor)
        self.stdout.write(
            self.style.SUCCESS(
                f"初始招聘汇总文档已发布：V{reference.version}，"
                f"包含 {reference.positions.count()} 个参考岗位。"
            )
        )
