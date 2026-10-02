"""QC 공통 타입: 판정 값, QC 컬럼, 게이트 결과 병합.

Phase 2, 3 게이트도 이 포맷을 그대로 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

RAW_SHEET_ORIGINAL = "Raw Data_원문"
RAW_SHEET_SUBSIDIARY = "Raw Data_전략법인"
RAW_SHEETS = (RAW_SHEET_ORIGINAL, RAW_SHEET_SUBSIDIARY)

QC_SHEET_FULL = "QC_Full"
QC_SHEET_CLEAN = "QC_Clean"
QC_SHEET_DROPPED = "QC_Dropped"
QC_SHEETS = (QC_SHEET_FULL, QC_SHEET_CLEAN, QC_SHEET_DROPPED)

# 두 Raw 시트를 한 시트로 합치므로 출처 추적용 컬럼을 둔다.
QC_TRACE_COLUMNS = ["QC_Source_Sheet", "QC_Source_Row"]
QC_COLUMNS = [
    "QC_Verdict",
    "QC_Rule",
    "QC_Reason",
    "QC_Confidence",
    "QC_Cluster_ID",
]

RULE_SEPARATOR = " | "


class Verdict(str, Enum):
    KEEP = "KEEP"
    FLAG = "FLAG"
    DROP = "DROP"


SEVERITY = {Verdict.KEEP: 0, Verdict.FLAG: 1, Verdict.DROP: 2}


@dataclass(frozen=True)
class RawRow:
    sheet: str
    row_number: int  # Excel 행 번호(헤더 = 1)
    values: dict[str, Any]

    @property
    def key(self) -> str:
        return f"{self.sheet}!{self.row_number}"


@dataclass(frozen=True)
class GateOutcome:
    """게이트 하나가 행 하나에 내린 결과. 규칙이 적용되지 않은 행은 만들지 않는다."""

    verdict: Verdict
    rule: str
    reason: str
    # 참고용(예: Gemini가 보고한 신뢰도). DROP 근거로 쓰지 않는다.
    confidence: int | None = None
    cluster_id: str | None = None


@dataclass(frozen=True)
class QCRecord:
    verdict: Verdict
    rule: str
    reason: str
    confidence: int | None
    cluster_id: str | None

    def as_cells(self) -> dict[str, Any]:
        return {
            "QC_Verdict": self.verdict.value,
            "QC_Rule": self.rule,
            "QC_Reason": self.reason,
            "QC_Confidence": self.confidence,
            "QC_Cluster_ID": self.cluster_id,
        }


KEEP_RECORD = QCRecord(Verdict.KEEP, "", "", None, None)


@dataclass
class GateContext:
    input_path: Path
    output_path: Path
    use_llm: bool = True
    workers: int | None = None
    scope_config_path: Path | None = None
    follower_config_path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def merge_outcomes(outcomes: list[GateOutcome]) -> QCRecord:
    """여러 게이트 결과를 한 행의 QC 값으로 합친다.

    - 판정은 가장 무거운 쪽(DROP > FLAG > KEEP).
    - QC_Rule은 모든 규칙을 기록한다(KEEP이어도 규칙이 있으면 감사용으로 남김).
    - 신뢰도는 최종 판정을 만든 첫 결과의 값.
    """

    if not outcomes:
        return KEEP_RECORD

    top = max(SEVERITY[o.verdict] for o in outcomes)
    verdict = next(v for v, s in SEVERITY.items() if s == top)

    rules = [o.rule for o in outcomes if o.rule]

    if len(outcomes) == 1:
        reason = outcomes[0].reason
    else:
        reason = RULE_SEPARATOR.join(
            f"[{o.rule}] {o.reason}" if o.rule else o.reason
            for o in outcomes
            if o.reason
        )

    deciding = next(o for o in outcomes if SEVERITY[o.verdict] == top)
    cluster_id = next(
        (o.cluster_id for o in outcomes if o.cluster_id), None
    )

    return QCRecord(
        verdict=verdict,
        rule=RULE_SEPARATOR.join(rules),
        reason=reason,
        confidence=deciding.confidence,
        cluster_id=cluster_id,
    )
