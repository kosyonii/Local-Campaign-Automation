"""팔로워/구독자 게이트 단위 테스트."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quality_control.follower_gate import (  # noqa: E402
    DEFAULT_FOLLOWER_CONFIG_PATH,
    RULE_BELOW,
    RULE_UNKNOWN,
    decide_row,
    load_follower_rule,
    parse_followers,
)
from quality_control.schema import (  # noqa: E402
    RAW_SHEET_ORIGINAL,
    RAW_SHEET_SUBSIDIARY,
    RawRow,
    Verdict,
)

COMMENT_WIDGET = "1.1. Comment 기준_Export용"


@pytest.fixture(scope="module")
def rule():
    return load_follower_rule(DEFAULT_FOLLOWER_CONFIG_PATH)


def make_row(
    followers,
    widget=COMMENT_WIDGET,
    channel="INSTAGRAM",
    sheet=RAW_SHEET_ORIGINAL,
    **extra,
):
    return RawRow(
        sheet=sheet,
        row_number=2,
        values={
            "source_widget": widget,
            "snType column": channel,
            "Sender Follower Count": followers,
            **extra,
        },
    )


def test_below_threshold_is_dropped(rule):
    outcome = decide_row(make_row("99511"), rule)
    assert outcome.verdict is Verdict.DROP
    assert outcome.rule == RULE_BELOW
    assert "99,511" in outcome.reason


def test_at_or_above_threshold_has_no_outcome(rule):
    assert decide_row(make_row("100000"), rule) is None
    assert decide_row(make_row(670512), rule) is None


@pytest.mark.parametrize("value", ["0", 0, 0.0, None, "", "  ", "n/a", "-5"])
def test_zero_or_unreadable_is_flagged_not_dropped(rule, value):
    outcome = decide_row(make_row(value), rule)
    assert outcome.verdict is Verdict.FLAG
    assert outcome.rule == RULE_UNKNOWN


def test_profile_unavailable_is_flagged_even_with_small_number(rule):
    outcome = decide_row(
        make_row("120", **{"Sender Profile Available": False}), rule
    )
    assert outcome.verdict is Verdict.FLAG


@pytest.mark.parametrize("channel", ["TWITTER", "INSTAGRAM", "YOUTUBE", "instagram"])
def test_target_channels_apply(rule, channel):
    assert decide_row(make_row("500", channel=channel), rule).verdict is Verdict.DROP


@pytest.mark.parametrize("channel", ["FACEBOOK", "TIKTOK", None])
def test_other_channels_are_ignored(rule, channel):
    assert decide_row(make_row("500", channel=channel), rule) is None
    assert decide_row(make_row("0", channel=channel), rule) is None


@pytest.mark.parametrize(
    "widget",
    [
        "1.2. Reply 기준_Export용",
        "1.3. Repost 기준_Export용",
        "3. Partner X",
        "4. GCL IG",
        None,
    ],
)
def test_other_widgets_are_ignored_by_default(rule, widget):
    assert decide_row(make_row("500", widget=widget), rule) is None


def test_subsidiary_sheet_is_never_touched(rule):
    row = make_row("500", sheet=RAW_SHEET_SUBSIDIARY)
    assert decide_row(row, rule) is None


def test_config_validation(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("threshold: 0\nchannels: [X]\nwidgets: ['1.']\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_follower_rule(bad)


def test_parse_followers_handles_commas_and_bool():
    assert parse_followers("1,234") == 1234
    assert parse_followers(True) is None
