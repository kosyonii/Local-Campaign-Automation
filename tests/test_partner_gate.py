"""파트너 게이트 단위 테스트. Gemini는 가짜 judge로 대체한다."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quality_control import run as qc_run  # noqa: E402
from quality_control.partner_gate import (  # noqa: E402
    DEFAULT_PARTNER_CONFIG_PATH,
    Judgement,
    PartnerQuery,
    find_samsung_terms,
    load_partner_config,
    run_partner_gate,
)
from quality_control.schema import (  # noqa: E402
    RAW_SHEET_ORIGINAL,
    RAW_SHEET_SUBSIDIARY,
    GateContext,
    RawRow,
    Verdict,
)

PARTNER_X = "3. Partner X"


@pytest.fixture(scope="module")
def config():
    return load_partner_config(DEFAULT_PARTNER_CONFIG_PATH)


def row(text, number=2, widget=PARTNER_X, sheet=RAW_SHEET_ORIGINAL, **extra):
    values = {
        "source_widget": widget,
        "Conversation Stream": text,
        "Sender Screen Name": "partner_acct",
        "snType column": "TWITTER",
        **extra,
    }
    return RawRow(sheet=sheet, row_number=number, values=values)


def ctx(tmp_path, use_llm=True):
    source = tmp_path / "in.xlsx"
    source.write_bytes(b"x")
    return GateContext(
        input_path=source,
        output_path=tmp_path / "out.xlsx",
        use_llm=use_llm,
        workers=2,
    )


def judgement(verdict, evidence="", signals=(), reason="판정 이유", confidence=90):
    return Judgement(
        verdict=verdict,
        evidence=evidence,
        samsung_signals=tuple(signals),
        reason=reason,
        confidence=confidence,
    )


def run(rows, tmp_path, judge, use_llm=True):
    return run_partner_gate(rows, ctx(tmp_path, use_llm), judge=judge)


def never_called(query):  # pragma: no cover - 호출되면 실패
    raise AssertionError(f"LLM이 호출되면 안 됨: {query.key}")


# --- 사전 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Get the new Samsung phone",
        "#GalaxyZFold8 launch",  # 붙여 쓴 해시태그
        "삼성전자가 발표했습니다",  # 한국어 조사
        "Ｓａｍｓｕｎｇ ＴＶ",  # 전각
        "サムスンの新製品",
        "سامسونج جالاكسي",
        "Try One UI 8 today",
        "Z Flip8 review",
        "the Knox security suite",
    ],
)
def test_samsung_terms_hit(config, text):
    assert find_samsung_terms(text, config)


@pytest.mark.parametrize(
    "text",
    [
        "Michael Carrick provided an injury update",
        "Visit Knoxville this weekend",  # Knox 단어 경계
        "Your Perfect Number Starts Here",
        "",
    ],
)
def test_samsung_terms_miss(config, text):
    assert not find_samsung_terms(text, config)


# --- 판정 ---------------------------------------------------------------------


def test_keyword_hit_keeps_without_calling_llm(tmp_path):
    out = run([row("Samsung Galaxy S26 deal")], tmp_path, never_called)
    assert out["Raw Data_원문!2"].verdict is Verdict.KEEP
    assert out["Raw Data_원문!2"].rule == "PARTNER_SAMSUNG_KW"


def test_account_name_counts_as_keyword(tmp_path):
    r = row("New offers", **{"Sender Screen Name": "SamsungMobile"})
    assert run([r], tmp_path, never_called)["Raw Data_원문!2"].verdict is Verdict.KEEP


def test_unrelated_with_verified_evidence_is_dropped(tmp_path):
    text = "Michael Carrick has provided an injury update on Rashford"

    def judge(q):
        return judgement("UNRELATED_TO_SAMSUNG", evidence="injury update on Rashford")

    out = run([row(text)], tmp_path, judge)["Raw Data_원문!2"]
    assert out.verdict is Verdict.DROP
    assert out.rule == "PARTNER_UNRELATED"
    assert "injury update on Rashford" in out.reason
    assert out.confidence == 90


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"evidence": "text that is not in the post"}, "원문에서 확인되지 않음"),
        ({"evidence": ""}, "비어 있음"),
        ({"evidence": "injury update", "signals": ["Galaxy"]}, "당사 신호"),
    ],
)
def test_unverified_drop_becomes_flag(tmp_path, kwargs, expected):
    def judge(q):
        return judgement(
            "UNRELATED_TO_SAMSUNG",
            evidence=kwargs["evidence"],
            signals=kwargs.get("signals", ()),
        )

    out = run([row("Rashford injury update today")], tmp_path, judge)["Raw Data_원문!2"]
    assert out.verdict is Verdict.FLAG
    assert out.rule == "PARTNER_DROP_UNVERIFIED"
    assert expected in out.reason


def test_evidence_check_ignores_case_and_spacing(tmp_path):
    def judge(q):
        return judgement("UNRELATED_TO_SAMSUNG", evidence="RASHFORD   injury")

    out = run([row("Rashford injury update")], tmp_path, judge)["Raw Data_원문!2"]
    assert out.verdict is Verdict.DROP


@pytest.mark.parametrize(
    "verdict, rule",
    [
        ("SAMSUNG_RELATED", "PARTNER_LLM_RELATED"),
        ("UNCLEAR", "PARTNER_LLM_UNCLEAR"),
    ],
)
def test_related_or_unclear_is_flagged(tmp_path, verdict, rule):
    out = run(
        [row("Some neutral post about phones")],
        tmp_path,
        lambda q: judgement(verdict),
    )["Raw Data_원문!2"]
    assert out.verdict is Verdict.FLAG
    assert out.rule == rule


def test_no_llm_flags_instead_of_dropping(tmp_path):
    out = run([row("Rashford injury update")], tmp_path, never_called, use_llm=False)
    assert out["Raw Data_원문!2"].verdict is Verdict.FLAG
    assert out["Raw Data_원문!2"].rule == "PARTNER_LLM_UNAVAILABLE"
    assert "--no-llm" in out["Raw Data_원문!2"].reason


def test_llm_error_flags_that_row_only(tmp_path):
    def judge(q):
        if "boom" in q.text:
            raise RuntimeError("503")
        return judgement("UNRELATED_TO_SAMSUNG", evidence="nothing special")

    out = run(
        [row("boom post here", number=2), row("nothing special here", number=3)],
        tmp_path,
        judge,
    )
    assert out["Raw Data_원문!2"].rule == "PARTNER_LLM_UNAVAILABLE"
    assert "503" in out["Raw Data_원문!2"].reason
    assert out["Raw Data_원문!3"].verdict is Verdict.DROP


@pytest.mark.parametrize("text", ["", "👇", " ", "https://t.co/abc123 https://t.co/x"])
def test_text_too_short_is_flagged_without_llm(tmp_path, text):
    out = run([row(text)], tmp_path, never_called)["Raw Data_원문!2"]
    assert out.verdict is Verdict.FLAG
    assert out.rule == "PARTNER_NO_TEXT"


def test_query_carries_account_bio_and_media(tmp_path):
    seen: list[PartnerQuery] = []

    def judge(q):
        seen.append(q)
        return judgement("UNCLEAR")

    run(
        [
            row(
                "Look at this",
                **{"Sender Bio": "Official account", "Media URL": "https://x/y.jpg"},
            )
        ],
        tmp_path,
        judge,
    )
    assert seen[0].account == "partner_acct"
    assert seen[0].bio == "Official account"
    assert seen[0].has_media is True


@pytest.mark.parametrize("channel", ["INSTAGRAM", "YOUTUBE", "TIKTOK"])
def test_non_x_channels_without_keyword_are_flagged_without_llm(tmp_path, channel):
    r = row("Ernest Sim shares how Grain puts AI to work", **{"snType column": channel})
    out = run([r], tmp_path, never_called)["Raw Data_원문!2"]
    assert out.verdict is Verdict.FLAG
    assert out.rule == "PARTNER_MEDIA_CHANNEL"


def test_non_x_channel_with_keyword_is_still_kept(tmp_path):
    r = row("Samsung Galaxy deal", **{"snType column": "YOUTUBE"})
    assert run([r], tmp_path, never_called)["Raw Data_원문!2"].verdict is Verdict.KEEP


# --- 대상 범위 ----------------------------------------------------------------


@pytest.mark.parametrize(
    "widget",
    ["1.1. Comment 기준_Export용", "4. GCL IG", "2. 전략법인 전수조사 X", None],
)
def test_other_widgets_are_ignored(tmp_path, widget):
    assert run([row("Rashford injury", widget=widget)], tmp_path, never_called) == {}


def test_subsidiary_sheet_is_ignored(tmp_path):
    r = row("Rashford injury", sheet=RAW_SHEET_SUBSIDIARY)
    assert run([r], tmp_path, never_called) == {}


@pytest.mark.parametrize("widget", ["3. Partner IG", "3. Partner YT", "3. Partner TT"])
def test_all_partner_widgets_apply(tmp_path, widget):
    out = run([row("Samsung deal", widget=widget)], tmp_path, never_called)
    assert out["Raw Data_원문!2"].verdict is Verdict.KEEP


# --- 설정 / CLI ---------------------------------------------------------------


def test_config_validation(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("widgets: ['3.']\nsamsung_terms: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_partner_config(bad)


def test_partner_is_not_in_default_gates():
    assert "partner" in qc_run.GATES
    assert "partner" not in qc_run.DEFAULT_GATES


# --- 근거 인용 보정 / 안정화 ---------------------------------------------------


@pytest.mark.parametrize(
    "text, evidence",
    [
        ("She said “we remember those we lost” today", "‘we remember those we lost’"),  # 따옴표
        ("Q&amp;A with the CEO of Grain", "Q&A with the CEO of Grain"),  # HTML 엔티티
        ("Weekly update. Then a long middle part. Final summary here", "Weekly update ... Final summary here"),  # 말줄임
    ],
)
def test_evidence_check_is_tolerant(tmp_path, text, evidence):
    out = run(
        [row(text)],
        tmp_path,
        lambda q: judgement("UNRELATED_TO_SAMSUNG", evidence=evidence),
    )["Raw Data_원문!2"]
    assert out.verdict is Verdict.DROP


def test_stable_judge_retries_garbled_reason():
    from quality_control.partner_gate import make_stable_judge

    calls = []

    def call(q):
        calls.append(1)
        reason = "i gesimuleun" if len(calls) == 1 else "삼성과 무관한 게시물입니다."
        return judgement("UNCLEAR", reason=reason)

    result = make_stable_judge(call)(PartnerQuery("k", "text here", "a", "", False))
    assert result.reason == "삼성과 무관한 게시물입니다."
    assert len(calls) == 2


def test_stable_judge_requires_two_agreeing_drop_calls():
    from quality_control.partner_gate import make_stable_judge

    answers = [
        judgement("UNRELATED_TO_SAMSUNG", evidence="injury update"),
        judgement("UNCLEAR"),
    ]

    def call(q):
        return answers.pop(0)

    result = make_stable_judge(call)(
        PartnerQuery("k", "Rashford injury update today", "a", "", False)
    )
    assert result.verdict == "UNCLEAR"  # 합의 실패 -> FLAG 쪽 응답을 돌려줌


def test_stable_judge_confirms_drop_when_both_calls_agree():
    from quality_control.partner_gate import make_stable_judge

    calls = []

    def call(q):
        calls.append(1)
        return judgement("UNRELATED_TO_SAMSUNG", evidence="injury update")

    result = make_stable_judge(call)(
        PartnerQuery("k", "Rashford injury update today", "a", "", False)
    )
    assert result.verdict == "UNRELATED_TO_SAMSUNG"
    assert len(calls) == 2
