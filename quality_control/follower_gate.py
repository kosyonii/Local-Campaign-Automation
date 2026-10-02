"""Gate — 팔로워/구독자 기준 (Conversation Stream, X / IG / YT).

대상: 'Raw Data_원문' 시트 중 config/follower_rule.yaml의 widgets 접두어에 맞는 행.
판정 규칙은 config 머리말과 같다. 값이 0이거나 비었으면 DROP하지 않고 FLAG한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .schema import RAW_SHEET_ORIGINAL, GateContext, GateOutcome, RawRow, Verdict

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FOLLOWER_CONFIG_PATH = BASE_DIR / "config" / "follower_rule.yaml"

WIDGET_FIELD = "source_widget"
CHANNEL_FIELD = "snType column"
FOLLOWER_FIELD = "Sender Follower Count"
PROFILE_AVAILABLE_FIELD = "Sender Profile Available"

RULE_BELOW = "FOLLOWER_BELOW_THRESHOLD"
RULE_UNKNOWN = "FOLLOWER_UNKNOWN"


@dataclass(frozen=True)
class FollowerRule:
    threshold: int
    channels: frozenset[str]
    widgets: tuple[str, ...]


def load_follower_rule(path: Path) -> FollowerRule:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    threshold = data.get("threshold")
    channels = data.get("channels")
    widgets = data.get("widgets")

    if not isinstance(threshold, int) or threshold <= 0:
        raise ValueError(f"{path}: threshold는 양의 정수여야 합니다.")

    for name, value in (("channels", channels), ("widgets", widgets)):
        if not isinstance(value, list) or not value:
            raise ValueError(f"{path}: {name}는 비어 있지 않은 리스트여야 합니다.")

    return FollowerRule(
        threshold=threshold,
        channels=frozenset(str(c).strip().upper() for c in channels),
        widgets=tuple(str(w).strip() for w in widgets),
    )


def parse_followers(value: Any) -> float | None:
    """숫자로 읽히면 float, 비었거나 읽을 수 없으면 None."""

    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(",", "")

        if not text:
            return None

        try:
            number = float(text)
        except ValueError:
            return None

    if math.isnan(number) or number < 0:
        return None

    return number


def _profile_missing(value: Any) -> bool:
    return value is False or str(value).strip().lower() == "false"


def decide_row(row: RawRow, rule: FollowerRule) -> GateOutcome | None:
    """None이면 이 게이트가 말할 것이 없는 행(KEEP, 규칙 없음)."""

    if row.sheet != RAW_SHEET_ORIGINAL:
        return None

    widget = str(row.values.get(WIDGET_FIELD) or "").strip()
    channel = str(row.values.get(CHANNEL_FIELD) or "").strip().upper()

    if channel not in rule.channels or not widget.startswith(rule.widgets):
        return None

    followers = parse_followers(row.values.get(FOLLOWER_FIELD))

    if (
        followers is None
        or followers == 0
        or _profile_missing(row.values.get(PROFILE_AVAILABLE_FIELD))
    ):
        return GateOutcome(
            Verdict.FLAG,
            RULE_UNKNOWN,
            "팔로워/구독자 수가 0이거나 확인되지 않아 판단 불가"
            "(Sprinklr가 큰 계정에도 0을 주는 경우가 있어 DROP하지 않음)",
        )

    if followers < rule.threshold:
        return GateOutcome(
            Verdict.DROP,
            RULE_BELOW,
            f"팔로워/구독자 {int(followers):,}명으로 기준 "
            f"{rule.threshold:,}명 미만",
        )

    return None


def run_follower_gate(
    rows: list[RawRow], ctx: GateContext
) -> dict[str, GateOutcome]:
    rule = load_follower_rule(
        ctx.follower_config_path or DEFAULT_FOLLOWER_CONFIG_PATH
    )
    outcomes: dict[str, GateOutcome] = {}

    for row in rows:
        outcome = decide_row(row, rule)

        if outcome is not None:
            outcomes[row.key] = outcome

    return outcomes
