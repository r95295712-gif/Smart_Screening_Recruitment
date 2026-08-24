import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from recruitment.models import (
    DocumentPosition,
    PositionConfiguration,
    ReferenceDocument,
)


def normalize_position_title(value):
    normalized = (value or "").strip().casefold()
    normalized = normalized.replace("人工智能", "ai")
    normalized = normalized.replace("算法", "算法")
    return re.sub(r"[\s\-—_()（）/\\·,，、]+", "", normalized)


@dataclass
class MatchResult:
    status: str
    document_position: object = None
    method: str = ""
    score: float = 0
    ambiguous: bool = False
    candidates: tuple = ()


def match_position(position, document_positions=None):
    candidates = list(
        document_positions
        if document_positions is not None
        else DocumentPosition.objects.filter(
            is_active=True,
            reference_document__document_type=ReferenceDocument.DocumentType.JOB_SUMMARY_DOCX,
            reference_document__status=ReferenceDocument.Status.ACTIVE,
        ).select_related("reference_document")
    )
    target = normalize_position_title(position.name)
    exact = []
    scored = []
    for document_position in candidates:
        names = [document_position.title, *(document_position.aliases or [])]
        normalized_names = [normalize_position_title(name) for name in names if name]
        if target in normalized_names:
            exact.append(document_position)
            continue
        score = max(
            (SequenceMatcher(None, target, name).ratio() for name in normalized_names),
            default=0,
        )
        scored.append((score, document_position))

    if len(exact) == 1:
        return MatchResult(
            PositionConfiguration.MatchStatus.SUGGESTED,
            exact[0],
            "exact",
            1,
            candidates=tuple(exact),
        )
    if len(exact) > 1:
        return MatchResult(
            PositionConfiguration.MatchStatus.SUGGESTED,
            method="ambiguous_exact",
            score=1,
            ambiguous=True,
            candidates=tuple(exact),
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < 0.72:
        return MatchResult(PositionConfiguration.MatchStatus.PENDING)
    best_score = scored[0][0]
    close = [item[1] for item in scored if best_score - item[0] <= 0.03]
    if len(close) > 1:
        return MatchResult(
            PositionConfiguration.MatchStatus.SUGGESTED,
            method="ambiguous_similar",
            score=best_score,
            ambiguous=True,
            candidates=tuple(close),
        )
    return MatchResult(
        PositionConfiguration.MatchStatus.SUGGESTED,
        scored[0][1],
        "similar",
        best_score,
        candidates=(scored[0][1],),
    )


def apply_match_suggestion(position, document_positions=None, force=False):
    configuration, _ = PositionConfiguration.objects.get_or_create(position=position)
    if not force and configuration.match_status in {
        PositionConfiguration.MatchStatus.CONFIRMED,
        PositionConfiguration.MatchStatus.NO_MATCH,
    }:
        return configuration
    result = match_position(position, document_positions=document_positions)
    configuration.document_position = result.document_position
    configuration.match_status = result.status
    configuration.match_method = result.method
    configuration.match_score = result.score
    configuration.save()
    return configuration
