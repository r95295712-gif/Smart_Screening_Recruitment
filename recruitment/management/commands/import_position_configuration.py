import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from recruitment.models import (
    DocumentPosition,
    Position,
    PositionConfiguration,
    PositionJdDecision,
    ReferenceDocument,
)
from recruitment.services.configuration import confirm_jd, ensure_position_configuration
from recruitment.services.position_matching import normalize_position_title
from recruitment.services.reference_import import (
    apply_document_reviewers,
    parse_reviewer_mapping_xlsx,
)


class Command(BaseCommand):
    help = "导入当前招聘汇总、负责人表和已确认的岗位说明。"

    def add_arguments(self, parser):
        parser.add_argument("--actor", help="记录为操作人的用户名")
        parser.add_argument(
            "--replace-reviewers",
            action="store_true",
            help="用确认后的负责人表替换当前有效岗位的负责人关联",
        )

    def _actor(self, username):
        queryset = User.objects.filter(is_active=True)
        actor = queryset.filter(username=username).first() if username else None
        actor = actor or queryset.filter(role=User.Role.ADMIN).first() or queryset.first()
        if not actor:
            raise CommandError("请先创建一个可用的 HR 或管理员账号。")
        return actor

    def _reference(self, path, document_type, actor):
        content = path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        existing = ReferenceDocument.objects.filter(
            document_type=document_type,
            content_hash=content_hash,
        ).first()
        if existing:
            if existing.status != ReferenceDocument.Status.ACTIVE:
                ReferenceDocument.objects.filter(
                    document_type=document_type,
                    status=ReferenceDocument.Status.ACTIVE,
                ).exclude(pk=existing.pk).update(
                    status=ReferenceDocument.Status.ARCHIVED
                )
                existing.status = ReferenceDocument.Status.ACTIVE
                existing.published_by = actor
                existing.published_at = timezone.now()
                existing.save(
                    update_fields=["status", "published_by", "published_at"]
                )
            return existing, content, False
        version = (
            ReferenceDocument.objects.filter(document_type=document_type)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
            or 0
        ) + 1
        ReferenceDocument.objects.filter(
            document_type=document_type,
            status=ReferenceDocument.Status.ACTIVE,
        ).update(status=ReferenceDocument.Status.ARCHIVED)
        with path.open("rb") as handle:
            reference = ReferenceDocument.objects.create(
                name=path.name,
                document_type=document_type,
                file=File(handle, name=path.name),
                content_hash=content_hash,
                version=version,
                status=ReferenceDocument.Status.ACTIVE,
                uploaded_by=actor,
                published_by=actor,
                published_at=timezone.now(),
            )
        return reference, content, True

    @transaction.atomic
    def handle(self, *args, **options):
        root = Path(settings.BASE_DIR)
        docx_path = root / "docs" / "招聘信息汇总.docx"
        xlsx_candidates = [
            path
            for path in (
                root
                / "outputs"
                / "01a00e3e-98b7-76d2-99a3-66ae41444da9"
            ).glob("*北森标准.xlsx")
            if not path.name.startswith("~$")
        ]
        data_path = root / "analysis" / "recruitment_summary" / "data.json"
        decisions_path = (
            root / "analysis" / "recruitment_summary" / "jd_decisions.json"
        )
        if not docx_path.exists() or not xlsx_candidates:
            raise CommandError("未找到当前招聘汇总文档或确认后的负责人表。")
        actor = self._actor(options.get("actor"))

        doc_reference, _, doc_created = self._reference(
            docx_path,
            ReferenceDocument.DocumentType.JOB_SUMMARY_DOCX,
            actor,
        )
        data = json.loads(data_path.read_text(encoding="utf-8"))
        if doc_created or not doc_reference.positions.exists():
            DocumentPosition.objects.bulk_create(
                [
                    DocumentPosition(
                        reference_document=doc_reference,
                        title=item["title"],
                        normalized_title=normalize_position_title(item["title"]),
                        aliases=item.get("aliases", []),
                        jd=item.get("content", ""),
                        source_section=item.get("department", ""),
                        metadata={
                            "owners": item.get("owners", []),
                            "status": item.get("status", ""),
                        },
                    )
                    for item in data.get("document_jobs", [])
                ]
            )

        xlsx_reference, xlsx_content, _ = self._reference(
            xlsx_candidates[0],
            ReferenceDocument.DocumentType.REVIEWER_MAPPING_XLSX,
            actor,
        )
        xlsx_reference.positions.all().delete()
        DocumentPosition.objects.bulk_create(
            [
                DocumentPosition(
                    reference_document=xlsx_reference,
                    title=item["title"],
                    normalized_title=normalize_position_title(item["title"]),
                    aliases=item.get("aliases", []),
                    jd="",
                    source_section=item.get("source_section", ""),
                    metadata=item.get("metadata", {}),
                )
                for item in parse_reviewer_mapping_xlsx(xlsx_content)
            ]
        )

        decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
        document_positions = list(doc_reference.positions.all())
        imported = 0
        reviewers = 0
        for position in Position.objects.filter(status=Position.Status.ACTIVE):
            configuration = ensure_position_configuration(position)
            decision_data = decisions.get(position.name)
            if not decision_data:
                continue
            expected_title = normalize_position_title(
                decision_data.get("document_title", "")
            )
            document_position = next(
                (
                    item
                    for item in document_positions
                    if expected_title
                    in {
                        normalize_position_title(item.title),
                        *(
                            normalize_position_title(alias)
                            for alias in item.aliases or []
                        ),
                    }
                ),
                None,
            )
            configuration.document_position = document_position
            configuration.match_status = (
                PositionConfiguration.MatchStatus.CONFIRMED
                if document_position
                else PositionConfiguration.MatchStatus.NO_MATCH
            )
            configuration.match_method = "initial_import"
            configuration.match_score = 1 if document_position else 0
            configuration.matched_by = actor
            configuration.matched_at = timezone.now()
            configuration.save()
            if options.get("replace_reviewers"):
                position.reviewer_links.all().delete()
            reviewers += apply_document_reviewers(configuration, actor)

            if not position.jd_decisions.filter(is_current=True).exists():
                decision_type = {
                    "采用北森": PositionJdDecision.DecisionType.BEISEN,
                    "合并JD": PositionJdDecision.DecisionType.MERGED,
                }.get(
                    decision_data.get("decision"),
                    PositionJdDecision.DecisionType.MANUAL,
                )
                confirmed_jd = (
                    decision_data.get("evaluation_jd")
                    or position.evaluation_jd
                    or position.source_jd
                )
                confirm_jd(
                    position,
                    decision_type,
                    actor,
                    confirmed_jd=confirmed_jd,
                )
                imported += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"已导入岗位说明记录 {imported} 条，新增负责人关联 {reviewers} 条。"
            )
        )
