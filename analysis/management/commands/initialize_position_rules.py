from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from analysis.models import AnalysisJob, PositionRuleVersion, RuleGenerationOperation
from analysis.services.rules import create_initial_published_rule
from recruitment.models import Position, PositionConfiguration, PositionJdDecision
from reviews.models import ReviewBatch


class Command(BaseCommand):
    help = "根据北森岗位说明生成并发布初始岗位规则 V0。"

    def add_arguments(self, parser):
        parser.add_argument("--actor", help="记录为操作人的用户名")
        parser.add_argument(
            "--reset",
            action="store_true",
            help="清除现有分析、审核、岗位说明确认和规则后重新生成",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="确认执行 --reset 的数据清理",
        )
        parser.add_argument(
            "--delete-analysis-history",
            action="store_true",
            help="同时删除引用旧规则的分析任务和审核任务",
        )

    def _actor(self, username):
        actor = None
        if username:
            actor = User.objects.filter(username=username, is_active=True).first()
        actor = (
            actor
            or User.objects.filter(is_active=True, role=User.Role.ADMIN).first()
            or User.objects.filter(is_active=True).first()
        )
        if not actor:
            raise CommandError("系统中没有可用于记录自动配置的有效用户。")
        return actor

    def _reset(self, delete_analysis_history):
        has_analysis_history = AnalysisJob.objects.exists() or ReviewBatch.objects.exists()
        if has_analysis_history and not delete_analysis_history:
            raise CommandError(
                "旧规则仍被分析或审核记录引用。若确认这些均为测试数据，"
                "请额外提供 --delete-analysis-history。"
            )
        with transaction.atomic():
            if delete_analysis_history:
                ReviewBatch.objects.all().delete()
                AnalysisJob.objects.all().delete()
            RuleGenerationOperation.objects.all().delete()
            PositionRuleVersion.objects.all().delete()
            PositionJdDecision.objects.all().delete()
            Position.objects.update(evaluation_jd="")
            PositionConfiguration.objects.update(ready_at=None)

    def handle(self, *args, **options):
        if options["reset"] and not options["yes"]:
            raise CommandError("执行 --reset 时必须同时提供 --yes。")
        actor = self._actor(options.get("actor"))
        if options["reset"]:
            self._reset(options["delete_analysis_history"])
            self.stdout.write("现有岗位说明确认和规则已清除。")
            if options["delete_analysis_history"]:
                self.stdout.write("引用旧规则的分析任务和审核任务也已清除。")

        created = 0
        skipped = 0
        failures = []
        positions = Position.objects.filter(
            status=Position.Status.ACTIVE,
        ).order_by("name")
        for position in positions:
            try:
                rule, was_created = create_initial_published_rule(position, actor)
                if was_created:
                    created += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"{position.name}：已发布规则 V{rule.version}")
                    )
                else:
                    skipped += 1
                    self.stdout.write(f"{position.name}：已有规则，已跳过")
            except Exception as exc:
                failures.append((position.name, str(exc)))
                self.stderr.write(self.style.ERROR(f"{position.name}：{exc}"))

        self.stdout.write(
            f"处理完成：生成 {created} 个，跳过 {skipped} 个，失败 {len(failures)} 个。"
        )
        if failures:
            self.stderr.write("失败岗位可在模型服务恢复后重新执行本命令，无需再次 --reset。")
