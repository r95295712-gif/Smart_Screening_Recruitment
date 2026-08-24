import json
import re
from difflib import SequenceMatcher
from pathlib import Path


data = json.loads(
    Path(__file__).with_name("data.json").read_text(encoding="utf-8")
)
mapping = {
    "Amazon亚马逊运营": "亚马逊Amazon运营（中级）",
    "Temu运营": "Temu运营",
    "Tiktok店铺运营": "TK运营/Tiktok运营",
    "ai算法工程师": "AI工程师",
    "产品经理（跨境电商方向）": "产品经理（出海赛道/双休）/产品开发经理（出海赛道/双休）",
    "产品设计师": "产品设计师",
    "海外社媒运营": "海外社交媒体运营/新媒体运营（面向海外）/海外社媒运营/社交媒体推广专员",
    "跨境电商运营（应届生可投）": "跨境电商运营（应届生可投）",
    "采购开发工程师": "采购开发工程师",
}


def lines(value):
    result = []
    for line in value.splitlines():
        line = re.sub(r"^\s*[一二三四五六七八九十]+[、.]\s*", "", line)
        line = re.sub(r"^\s*\d+[、.]\s*", "", line)
        line = re.sub(r"^(岗位职责|任职要求|职位要求)[：:]?", "", line)
        line = re.sub(r"\s+", "", line).strip("；。:：")
        if line:
            result.append(line)
    return result


for beisen_title, document_title in mapping.items():
    beisen_job = next(job for job in data["beisen_jobs"] if job["title"] == beisen_title)
    document_job = next(
        job for job in data["document_jobs"] if job["title"] == document_title
    )
    source_lines = lines(beisen_job["content"])
    document_lines = lines(document_job["content"])
    matcher = SequenceMatcher(None, source_lines, document_lines)
    print(f"\n### {beisen_title} -> {document_title}")
    for tag, source_start, source_end, document_start, document_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        if source_start != source_end:
            print("北森独有/不同：")
            for line in source_lines[source_start:source_end]:
                print(f"  - {line}")
        if document_start != document_end:
            print("文档独有/不同：")
            for line in document_lines[document_start:document_end]:
                print(f"  - {line}")
