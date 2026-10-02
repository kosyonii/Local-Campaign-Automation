"""Gate A 일관성 보강 테스트: 근거 인용 보정, 깨진 응답 재시도, DROP 합의."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quality_control.scope_gate import (  # noqa: E402
    Judgement,
    ScopeQuery,
    evidence_in_text,
    make_stable_judge,
    response_is_clean,
)

NUL = chr(0)


def query(text="Samsung TV is great"):
    return ScopeQuery(key="k", text=text, bio="", matched={"TV": ["TV"]})


def judgement(
    verdict="NON_MOBILE_ONLY",
    evidence="Samsung TV is great",
    products=("TV",),
    mobile=(),
    reason="TV 홍보 게시물입니다.",
):
    return Judgement(
        verdict=verdict,
        evidence=evidence,
        non_mobile_products=tuple(products),
        mobile_products=tuple(mobile),
        reason=reason,
        confidence=90,
    )


# --- 근거 인용 보정 -----------------------------------------------------------


@pytest.mark.parametrize(
    "evidence, text",
    [
        # 따옴표 종류가 바뀜 (“ ” -> ‘ ’)
        (
            "dual VDE for both ‘Safety for Eyes’ and ‘Circadian Rhythm’",
            "dual VDE for both “Safety for Eyes” and “Circadian Rhythm”",
        ),
        # HTML 엔티티가 풀림
        ("뮤지컬 <사랑의 불시착: 라이브 IN 서울> 삼성 TV 플러스", "뮤지컬 &lt;사랑의 불시착: 라이브 IN 서울&gt; 삼성 TV 플러스 추석"),
        # 떨어진 두 구절을 ...로 이어 붙임
        (
            "오디세이 캠페인 영상을 통해 만나보세요. ... #삼성TV #삼성OLED",
            "오디세이 캠페인 영상을 통해 만나보세요. Vision AI 컴패니언 & T1과 함께 #삼성TV #삼성OLED",
        ),
        # 대소문자, 공백, 이모지, 대시
        ("Better  TV —  every beat", "better tv - every beat 🎶"),
    ],
)
def test_evidence_in_text_tolerates_cosmetic_differences(evidence, text):
    assert evidence_in_text(evidence, text)


@pytest.mark.parametrize(
    "evidence, text",
    [
        ("", "Samsung TV is great"),
        ("   ", "Samsung TV is great"),
        ("Samsung phone is great", "Samsung TV is great"),  # 다른 내용
        ("a…b", "a first then b second"),  # 조각이 4자 미만
        ("Samsung TV is great ... and something invented", "Samsung TV is great"),  # 한 조각이 원문에 없음
        ("TV", "Samsung TV is great"),  # 너무 짧은 근거
    ],
)
def test_evidence_in_text_rejects_wrong_or_empty(evidence, text):
    assert not evidence_in_text(evidence, text)


# --- 깨끗한 응답 --------------------------------------------------------------


def test_clean_response_requires_verified_evidence_for_non_mobile():
    assert response_is_clean(judgement(), query())
    assert not response_is_clean(judgement(evidence="invented text here"), query())


def test_other_verdicts_do_not_need_evidence():
    j = judgement(verdict="MOBILE_RELATED", evidence="", products=(), mobile=("Galaxy",))
    assert response_is_clean(j, query())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"evidence": "Samsung" + NUL + " TV is great"},  # 제어문자 섞임
        {"reason": "TV" + NUL + "홍보"},
        {"reason": "i gesimuleun TV gesimul-imnida"},  # 한글 없음
    ],
)
def test_garbled_response_is_not_clean(kwargs):
    assert not response_is_clean(judgement(**kwargs), query())


# --- 재시도 / 합의 ------------------------------------------------------------


def scripted(responses):
    """호출할 때마다 responses를 차례로 돌려주는 call과 호출 기록."""

    calls = []

    def call(q):
        calls.append(q.key)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    return call, calls


def test_agreeing_clean_drop_candidates_are_confirmed():
    call, calls = scripted([judgement(), judgement()])
    result = make_stable_judge(call)(query())
    assert result.verdict == "NON_MOBILE_ONLY"
    assert len(calls) == 2  # 합의용 2회


def test_second_call_disagreement_downgrades_to_that_response():
    call, calls = scripted(
        [
            judgement(),
            judgement(verdict="MOBILE_RELATED", evidence="", products=(), mobile=("Galaxy",)),
        ]
    )
    result = make_stable_judge(call)(query())
    assert result.verdict == "MOBILE_RELATED"


def test_second_call_with_unverified_evidence_downgrades():
    call, _ = scripted([judgement(), judgement(evidence="invented quote text")])
    result = make_stable_judge(call, attempts=1)(query())
    assert result.verdict == "NON_MOBILE_ONLY"
    assert not response_is_clean(result, query())  # 판정 규칙이 FLAG로 처리


def test_non_drop_verdict_is_not_called_twice():
    j = judgement(verdict="UNCLEAR", evidence="", products=())
    call, calls = scripted([j])
    make_stable_judge(call)(query())
    assert len(calls) == 1


def test_unclean_response_is_retried_until_clean():
    bad = judgement(evidence="Samsung" + NUL + " TV is great")
    call, calls = scripted([bad, bad, judgement(), judgement()])
    result = make_stable_judge(call, attempts=3)(query())
    assert response_is_clean(result, query())
    assert len(calls) == 4  # 정상 응답까지 3회 + 합의 1회


def test_still_unclean_after_all_attempts_is_returned_for_flagging():
    bad = judgement(evidence="invented quote text")
    call, calls = scripted([bad])
    result = make_stable_judge(call, attempts=3)(query())
    assert result is bad
    assert len(calls) == 3


def test_consensus_of_one_disables_second_call():
    call, calls = scripted([judgement()])
    make_stable_judge(call, consensus=1)(query())
    assert len(calls) == 1
