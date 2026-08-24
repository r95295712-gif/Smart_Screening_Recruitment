import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

import django

django.setup()

from django.db import transaction

from recruitment.models import Position


DECISIONS = json.loads(
    Path(__file__).with_name("jd_decisions.json").read_text(encoding="utf-8")
)


@transaction.atomic
def apply_decisions():
    position_names = set(DECISIONS)
    positions = {
        position.name: position
        for position in Position.objects.select_for_update().filter(
            name__in=position_names
        )
    }
    missing = position_names - positions.keys()
    if missing:
        raise RuntimeError(f"缺少岗位：{'、'.join(sorted(missing))}")

    for name, decision in DECISIONS.items():
        position = positions[name]
        if decision["jd_source"] == "beisen":
            position.evaluation_jd = position.source_jd
        elif decision["jd_source"] == "merged":
            position.evaluation_jd = decision["evaluation_jd"]
        else:
            raise RuntimeError(f"{name} 的JD来源无效：{decision['jd_source']}")
        position.save(update_fields=["evaluation_jd"])

    return positions


if __name__ == "__main__":
    updated = apply_decisions()
    for name in DECISIONS:
        position = updated[name]
        print(
            f"{name}: source_jd={len(position.source_jd)} "
            f"evaluation_jd={len(position.evaluation_jd)}"
        )
