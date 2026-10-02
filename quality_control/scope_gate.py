"""Gate A — 전략법인 비모바일 scope (태스크 2).

대상: 'Raw Data_전략법인' 시트만. 다른 시트는 건드리지 않는다.

판정 (config/product_scope.yaml 머리말과 같은 흐름)
    비모바일 용어 없음                         -> KEEP
    비모바일 용어 + 강한 모바일 신호            -> KEEP  (규칙만 기록, 감사용)
    비모바일 용어 + 약한 모바일 신호만          -> FLAG
    비모바일 용어 + 모바일 신호 없음            -> Gemini 텍스트 판정
        NON_MOBILE_ONLY + 코드 검증 통과        -> DROP
        그 외 / Gemini 실패 / --no-llm          -> FLAG

DROP은 (1) 비모바일 용어 히트, (2) 모바일 신호 없음, (3) Gemini가 NON_MOBILE_ONLY,
(4) Gemini가 인용한 근거가 원문에 실제로 있고 비모바일 제품을 지목 — 네 가지가 모두
맞아야만 한다. Gemini confidence 숫자는 판정에 쓰지 않는다(QC_Confidence에 참고용으로만 기록).
"""

from __future__ import annotations

import html
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from checkpoint_utils import (
    PeriodicCheckpoint,
    checkpoint_json_path,
    load_checkpoint_json,
    source_fingerprint,
)

from .schema import RAW_SHEET_SUBSIDIARY, GateContext, GateOutcome, RawRow, Verdict

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SCOPE_CONFIG_PATH = BASE_DIR / "config" / "product_scope.yaml"
DEFAULT_SYSTEM_PROMPT_PATH = BASE_DIR / "prompts" / "qc_scope_system_prompt.txt"

CHECKPOINT_TAG = "qc_scope"

TEXT_FIELD = "Conversation Stream"
# URL은 스캔하지 않는다(예: instagram.com/tv/ 경로가 TV로 오탐).
ACCOUNT_FIELDS = ("User Name", "Author Screen Name", "Sender Screen Name")
BIO_FIELD = "Sender Bio"

RULE_NONMOBILE_DROP = "SCOPE_NONMOBILE_ONLY"
RULE_WITH_MOBILE = "SCOPE_NONMOBILE_KW_WITH_MOBILE"
RULE_WEAK_MOBILE = "SCOPE_NONMOBILE_KW_WEAK_MOBILE"
RULE_LLM_MOBILE = "SCOPE_LLM_MOBILE"
RULE_LLM_UNCLEAR = "SCOPE_LLM_UNCLEAR"
RULE_DROP_UNVERIFIED = "SCOPE_DROP_UNVERIFIED"
RULE_LLM_UNAVAILABLE = "SCOPE_LLM_UNAVAILABLE"

VERDICT_NON_MOBILE = "NON_MOBILE_ONLY"
VERDICT_MOBILE = "MOBILE_RELATED"
VERDICT_UNCLEAR = "UNCLEAR"
JUDGE_VERDICTS = (VERDICT_NON_MOBILE, VERDICT_MOBILE, VERDICT_UNCLEAR)

JUDGE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(JUDGE_VERDICTS)},
        "evidence": {"type": "string"},
        "non_mobile_products": {
            "type": "array",
            "items": {"type": "string"},
        },
        "mobile_products": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reason": {"type": "string"},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": [
        "verdict",
        "evidence",
        "non_mobile_products",
        "mobile_products",
        "reason",
        "confidence",
    ],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# 사전 로딩 / 매칭
# ---------------------------------------------------------------------------

_LATIN_ALNUM = "0-9A-Za-zÀ-ɏ"
_LATIN_ALNUM_RE = re.compile(f"[{_LATIN_ALNUM}]")
_ZERO_WIDTH_RE = re.compile("[​-‍⁠﻿]")
_JOINER = r"[\s\-_.]*"


def normalize_text(text: str) -> str:
    """NFKC 정규화 + 제로폭 문자 제거. 전각 ＴＶ 같은 표기를 맞춘다."""

    return _ZERO_WIDTH_RE.sub("", unicodedata.normalize("NFKC", text))


def normalize_for_containment(text: str) -> str:
    """근거 인용이 원문에 있는지 비교하기 위한 정규화(대소문자·공백 무시)."""

    return " ".join(normalize_text(text).casefold().split())


def compile_term(term: str) -> re.Pattern[str]:
    if term.startswith("re:"):
        return re.compile(term[3:], re.IGNORECASE)

    words = term.split()

    if not words:
        raise ValueError("빈 용어")

    body = _JOINER.join(re.escape(word) for word in words)
    left = (
        f"(?<![{_LATIN_ALNUM}])"
        if _LATIN_ALNUM_RE.match(words[0][0])
        else ""
    )
    right = (
        f"(?![{_LATIN_ALNUM}])"
        if _LATIN_ALNUM_RE.match(words[-1][-1])
        else ""
    )

    return re.compile(f"{left}{body}{right}", re.IGNORECASE)


@dataclass(frozen=True)
class TermGroup:
    name: str
    patterns: tuple[tuple[str, re.Pattern[str]], ...]

    def find(self, text: str) -> list[str]:
        """겹치지 않게 찾은 매칭 문자열(대소문자 무시 중복 제거, 등장 순서)."""

        found: dict[str, str] = {}

        for _term, pattern in self.patterns:
            for match in pattern.finditer(text):
                found.setdefault(match.group(0).casefold(), match.group(0))

        return list(found.values())


@dataclass(frozen=True)
class ScopeDictionary:
    nonmobile: tuple[TermGroup, ...]
    mobile_strong: TermGroup
    mobile_weak: TermGroup


def _build_group(name: str, terms: Any) -> TermGroup:
    if not isinstance(terms, list) or not terms:
        raise ValueError(f"{name}: terms는 비어 있지 않은 리스트여야 합니다.")

    compiled = []

    for term in terms:
        if not isinstance(term, str) or not term.strip():
            raise ValueError(f"{name}: 잘못된 용어 {term!r}")

        try:
            compiled.append((term, compile_term(term.strip())))
        except re.error as exc:
            raise ValueError(
                f"{name}: 정규식 오류 {term!r}: {exc}"
            ) from exc

    return TermGroup(name=name, patterns=tuple(compiled))


def load_scope_dictionary(path: Path) -> ScopeDictionary:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    for key in ("nonmobile", "mobile_strong", "mobile_weak"):
        if key not in data:
            raise ValueError(f"{path}: '{key}' 항목이 없습니다.")

    families = data["nonmobile"]

    if not isinstance(families, list) or not families:
        raise ValueError(f"{path}: nonmobile은 family 리스트여야 합니다.")

    return ScopeDictionary(
        nonmobile=tuple(
            _build_group(str(item.get("family")), item.get("terms"))
            for item in families
        ),
        mobile_strong=_build_group(
            "mobile_strong", data["mobile_strong"].get("terms")
        ),
        mobile_weak=_build_group(
            "mobile_weak", data["mobile_weak"].get("terms")
        ),
    )


@dataclass(frozen=True)
class ScopeScan:
    nonmobile: dict[str, list[str]]  # family -> 매칭 문자열
    strong: list[str]
    weak: list[str]

    @property
    def has_nonmobile(self) -> bool:
        return bool(self.nonmobile)


def scan_text(text: str, dictionary: ScopeDictionary) -> ScopeScan:
    normalized = normalize_text(text)

    return ScopeScan(
        nonmobile={
            group.name: hits
            for group in dictionary.nonmobile
            if (hits := group.find(normalized))
        },
        strong=dictionary.mobile_strong.find(normalized),
        weak=dictionary.mobile_weak.find(normalized),
    )


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value)


def row_scan_text(row: RawRow) -> str:
    """키워드를 찾을 텍스트: 본문 + 계정명."""

    parts = [_cell_text(row.values.get(TEXT_FIELD))]
    parts.extend(_cell_text(row.values.get(f)) for f in ACCOUNT_FIELDS)

    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Gemini 판정
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeQuery:
    key: str
    text: str
    bio: str
    matched: dict[str, list[str]]


@dataclass(frozen=True)
class Judgement:
    verdict: str
    evidence: str
    non_mobile_products: tuple[str, ...]
    mobile_products: tuple[str, ...]
    reason: str
    confidence: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "evidence": self.evidence,
            "non_mobile_products": list(self.non_mobile_products),
            "mobile_products": list(self.mobile_products),
            "reason": self.reason,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Judgement":
        verdict = data.get("verdict")

        if verdict not in JUDGE_VERDICTS:
            raise ValueError(f"알 수 없는 verdict: {verdict!r}")

        confidence = data.get("confidence")

        return cls(
            verdict=verdict,
            evidence=str(data.get("evidence") or ""),
            non_mobile_products=tuple(
                str(p) for p in data.get("non_mobile_products") or []
            ),
            mobile_products=tuple(
                str(p) for p in data.get("mobile_products") or []
            ),
            reason=str(data.get("reason") or ""),
            confidence=confidence if isinstance(confidence, int) else None,
        )


Judge = Callable[[ScopeQuery], Judgement]

_HANGUL_RE = re.compile("[가-힣]")
_HANGUL_JAMO_RE = re.compile("[ᄀ-ᇿ㄰-㆏ꥠ-꥿ힰ-퟿]")


def reason_is_garbled(reason: str) -> bool:
    """한국어 reason이 깨졌는지 본다.

    잡는 것: 한글이 없는 경우(로마자 표기로 대답), 자모가 낱개로 섞인 경우.
    못 잡는 것: 음절만 틀린 오타(예: '가잔제품').
    """

    return not _HANGUL_RE.search(reason) or bool(
        _HANGUL_JAMO_RE.search(reason)
    )


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ELLIPSIS_RE = re.compile(r"\.{3}|…")

# 같은 질의를 다시 불러도 되는 최대 횟수(깨진 응답, 검증 실패 인용)와,
# DROP을 확정하려면 서로 일치해야 하는 호출 횟수.
MAX_CLEAN_ATTEMPTS = 3
DROP_CONSENSUS_CALLS = 2


def _alnum_key(text: str) -> str:
    """HTML 엔티티를 풀고 글자·숫자만 남긴 비교용 문자열(따옴표·대시·이모지·공백 무시)."""

    normalized = unicodedata.normalize("NFKC", html.unescape(text)).casefold()

    return "".join(c for c in normalized if unicodedata.category(c)[0] in "LN")


def evidence_in_text(evidence: str, text: str, min_chars: int = 4) -> bool:
    """Gemini가 인용한 근거가 원문에 실제로 있는지.

    모델이 따옴표 종류를 바꾸거나(“ -> ‘), &lt; 같은 HTML 엔티티를 풀거나,
    떨어진 두 구절을 '...'로 이어 붙여도 통과한다. 조각마다 따로 검증하고
    모든 조각이 원문에 있어야 한다. 글자·숫자가 min_chars 미만인 조각은 근거로 쓰지 않는다.
    """

    fragments = [
        f
        for f in _ELLIPSIS_RE.split(evidence)
        if len(_alnum_key(f)) >= min_chars
    ]

    if not fragments:
        return False

    key = _alnum_key(text)

    return all(_alnum_key(f) in key for f in fragments)


def response_is_clean(judgement: Judgement, query: ScopeQuery) -> bool:
    """재호출 없이 쓸 수 있는 응답인지.

    제어문자가 섞이거나 reason이 깨졌거나, 비모바일 전용이라면서 근거가 원문에 없으면
    깨끗하지 않다. (비모바일 전용 외 판정의 근거는 쓰이지 않는다.)
    """

    if _CONTROL_CHAR_RE.search(judgement.evidence) or _CONTROL_CHAR_RE.search(
        judgement.reason
    ):
        return False

    if reason_is_garbled(judgement.reason):
        return False

    if judgement.verdict == VERDICT_NON_MOBILE:
        return _evidence_is_verified(judgement, query.text)[0]

    return True


def make_stable_judge(
    call: Judge,
    attempts: int = MAX_CLEAN_ATTEMPTS,
    consensus: int = DROP_CONSENSUS_CALLS,
) -> Judge:
    """한 번의 호출(call)을 일관성 있게 감싼다.

    1. 깨끗하지 않은 응답은 최대 attempts번까지 다시 부른다. 끝까지 깨끗하지 않으면
       마지막 응답을 그대로 돌려주고, 판정 규칙이 FLAG로 처리한다.
    2. 비모바일 전용(DROP 후보)은 consensus번 모두 비모바일 전용이고 깨끗해야 확정한다.
       하나라도 다르면 그 다른 응답을 돌려줘 FLAG가 되게 한다.
    """

    def obtain(query: ScopeQuery) -> Judgement:
        latest: Judgement | None = None

        for _ in range(max(1, attempts)):
            latest = call(query)

            if response_is_clean(latest, query):
                return latest

        assert latest is not None
        return latest

    def judge(query: ScopeQuery) -> Judgement:
        first = obtain(query)

        if first.verdict != VERDICT_NON_MOBILE or not response_is_clean(
            first, query
        ):
            return first

        for _ in range(max(1, consensus) - 1):
            other = obtain(query)

            if other.verdict != VERDICT_NON_MOBILE or not response_is_clean(
                other, query
            ):
                return other

        return first

    return judge


def build_user_message(query: ScopeQuery) -> str:
    matched = "; ".join(
        f"{family}: {', '.join(hits)}"
        for family, hits in query.matched.items()
    )

    return (
        "<post>\n"
        f"Conversation Stream:\n{query.text}\n\n"
        f"Account Bio: {query.bio or '(없음)'}\n"
        "</post>\n\n"
        f"사전에서 걸린 비모바일 용어: {matched}"
    )


def build_gemini_judge(
    system_prompt_path: Path = DEFAULT_SYSTEM_PROMPT_PATH,
) -> Judge:
    """기존 4단계의 create_genai_client / 모델 / 재시도 설정을 재사용한다.

    인증 정보가 없거나 패키지가 없으면 여기서 예외가 난다(호출부에서 안내).
    """

    # 임포트 시점 부작용을 피하려고 지연 임포트
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

    import time

    import llm_analysis_pipeline as lap

    client, types = lap.create_genai_client()
    config = types.GenerateContentConfig(
        system_instruction=Path(system_prompt_path).read_text(
            encoding="utf-8"
        ),
        temperature=lap.TEMPERATURE,
        max_output_tokens=lap.MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
        response_json_schema=JUDGE_RESPONSE_SCHEMA,
        # thinking_config는 일부러 지정하지 않는다. low/minimal로 두면 reason 깨짐은
        # 사라지지만 모바일 맥락 판정이 약해져(260927 행 205: 📱·SmartThings 원격 제어)
        # 12/12 NON_MOBILE_ONLY가 된다. 누락률이 우선이라 기본값을 유지한다.
    )

    def call(query: ScopeQuery) -> Judgement:
        last_exc: Exception | None = None

        for attempt in range(1, lap.MAX_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=lap.GEMINI_MODEL,
                    contents=build_user_message(query),
                    config=config,
                )
                text = getattr(response, "text", None)

                if not text:
                    raise ValueError("빈 응답")

                return Judgement.from_dict(json.loads(text))
            except Exception as exc:  # noqa: BLE001 - 재시도 여부를 아래서 판단
                last_exc = exc

                if attempt >= lap.MAX_RETRIES or not (
                    lap.is_retryable_api_error(exc)
                ):
                    break

                time.sleep(min(2 ** (attempt - 1), 8))

        assert last_exc is not None
        raise last_exc

    return make_stable_judge(call)


def run_judgements(
    queries: list[ScopeQuery],
    judge: Judge,
    workers: int,
    cached: dict[str, Judgement],
    on_result: Callable[[str, Judgement], None] | None = None,
) -> tuple[dict[str, Judgement], dict[str, str]]:
    """캐시에 없는 질의만 병렬 호출. (판정, 오류) 두 dict를 돌려준다."""

    judgements = dict(cached)
    errors: dict[str, str] = {}
    pending = [q for q in queries if q.key not in cached]

    if not pending:
        return judgements, errors

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(judge, q): q for q in pending}

        for future in as_completed(futures):
            query = futures[future]

            try:
                judgements[query.key] = future.result()
            except Exception as exc:  # noqa: BLE001
                errors[query.key] = f"{type(exc).__name__}: {exc}"
                continue

            if on_result is not None:
                on_result(query.key, judgements[query.key])

    return judgements, errors


def judge_with_checkpoint(
    queries: list[ScopeQuery],
    ctx: GateContext,
    config_path: Path,
    judge: Judge | None = None,
) -> tuple[dict[str, Judgement], dict[str, str]]:
    """기존 체크포인트 패턴(checkpoint_utils)으로 성공한 판정을 3분마다 저장한다.

    재실행하면 성공한 행은 다시 호출하지 않고, 실패한 행만 다시 시도한다.
    체크포인트 정리는 최종 Excel 저장 뒤 run.py가 한다.
    """

    checkpoint_path = checkpoint_json_path(ctx.output_path, CHECKPOINT_TAG)
    fingerprint = source_fingerprint(
        ctx.input_path, config_path, DEFAULT_SYSTEM_PROMPT_PATH
    )
    ctx.extra["scope_checkpoint_path"] = checkpoint_path

    cached: dict[str, Judgement] = {}
    saved = load_checkpoint_json(checkpoint_path, fingerprint)

    if saved is not None:
        for key, data in saved.get("judgements", {}).items():
            try:
                cached[key] = Judgement.from_dict(data)
            except ValueError:
                continue

        print(f"[CHECKPOINT] scope 판정 {len(cached)}건 복원")

    if judge is None:
        judge = build_gemini_judge()

    workers = ctx.workers
    if workers is None:
        import llm_analysis_pipeline as lap

        workers = lap.GEMINI_MAX_WORKERS

    checkpoint = PeriodicCheckpoint(checkpoint_path, fingerprint)
    results = dict(cached)

    def build_state() -> dict[str, Any]:
        return {"judgements": {k: v.to_dict() for k, v in results.items()}}

    def on_result(key: str, judgement: Judgement) -> None:
        results[key] = judgement
        checkpoint.maybe_save(build_state)

    judgements, errors = run_judgements(
        queries, judge, workers, cached, on_result
    )

    if errors:
        checkpoint.maybe_save(build_state, force=True)

    return judgements, errors


# ---------------------------------------------------------------------------
# 판정 규칙
# ---------------------------------------------------------------------------


def _describe_hits(hits: dict[str, list[str]]) -> str:
    return ", ".join(
        f"{family}({'/'.join(found[:3])})" for family, found in hits.items()
    )


def _evidence_is_verified(
    judgement: Judgement, full_text: str
) -> tuple[bool, str]:
    if len(_alnum_key(judgement.evidence)) < 4:
        return False, "근거 인용이 비어 있음"

    if not evidence_in_text(judgement.evidence, full_text):
        return False, "근거 인용이 원문에서 확인되지 않음"

    if not judgement.non_mobile_products:
        return False, "비모바일 제품이 지목되지 않음"

    if judgement.mobile_products:
        return False, (
            "모바일 제품도 언급됨: " + ", ".join(judgement.mobile_products)
        )

    return True, ""


def decide_row(
    scan: ScopeScan,
    full_text: str,
    judgement: Judgement | None,
    error: str | None,
) -> GateOutcome | None:
    """None이면 이 게이트가 말할 것이 없는 행(KEEP, 규칙 없음)."""

    if not scan.has_nonmobile:
        return None

    hits = _describe_hits(scan.nonmobile)

    if scan.strong:
        return GateOutcome(
            Verdict.KEEP,
            RULE_WITH_MOBILE,
            f"비모바일 용어 {hits}와 함께 모바일 신호 있음: "
            f"{', '.join(scan.strong[:3])}",
        )

    if scan.weak:
        return GateOutcome(
            Verdict.FLAG,
            RULE_WEAK_MOBILE,
            f"비모바일 용어 {hits}, 일반 모바일어({', '.join(scan.weak[:3])})도 "
            "있어 확인 필요",
        )

    if judgement is None:
        detail = error or "LLM 판정을 실행하지 않음"

        return GateOutcome(
            Verdict.FLAG,
            RULE_LLM_UNAVAILABLE,
            f"비모바일 용어 {hits}, LLM 판정 없음({detail})",
        )

    confidence = judgement.confidence

    if judgement.verdict == VERDICT_MOBILE:
        return GateOutcome(
            Verdict.FLAG,
            RULE_LLM_MOBILE,
            f"비모바일 용어 {hits}, LLM은 모바일 관련으로 판정: "
            f"{judgement.reason}",
            confidence,
        )

    if judgement.verdict == VERDICT_UNCLEAR:
        return GateOutcome(
            Verdict.FLAG,
            RULE_LLM_UNCLEAR,
            f"비모바일 용어 {hits}, LLM 판단 불가: {judgement.reason}",
            confidence,
        )

    verified, why_not = _evidence_is_verified(judgement, full_text)

    if not verified:
        return GateOutcome(
            Verdict.FLAG,
            RULE_DROP_UNVERIFIED,
            f"비모바일 용어 {hits}, LLM은 비모바일 전용이라 했으나 "
            f"DROP 조건 미충족({why_not}): {judgement.reason}",
            confidence,
        )

    return GateOutcome(
        Verdict.DROP,
        RULE_NONMOBILE_DROP,
        f"비모바일 용어 {hits}, 모바일 신호 없음. "
        f"LLM: {judgement.reason} / 근거: \"{judgement.evidence}\" / "
        f"제품: {', '.join(judgement.non_mobile_products)}",
        confidence,
    )


# ---------------------------------------------------------------------------
# 게이트 진입점
# ---------------------------------------------------------------------------


def run_scope_gate(
    rows: list[RawRow],
    ctx: GateContext,
    judge: Judge | None = None,
) -> dict[str, GateOutcome]:
    config_path = ctx.scope_config_path or DEFAULT_SCOPE_CONFIG_PATH
    dictionary = load_scope_dictionary(config_path)

    targets = [r for r in rows if r.sheet == RAW_SHEET_SUBSIDIARY]
    scans: dict[str, ScopeScan] = {}
    texts: dict[str, str] = {}
    queries: list[ScopeQuery] = []

    for row in targets:
        text = row_scan_text(row)
        scan = scan_text(text, dictionary)
        texts[row.key] = text
        scans[row.key] = scan

        if scan.has_nonmobile and not scan.strong and not scan.weak:
            queries.append(
                ScopeQuery(
                    key=row.key,
                    text=_cell_text(row.values.get(TEXT_FIELD)),
                    bio=_cell_text(row.values.get(BIO_FIELD)),
                    matched=scan.nonmobile,
                )
            )

    judgements: dict[str, Judgement] = {}
    errors: dict[str, str] = {}

    if queries and ctx.use_llm:
        judgements, errors = judge_with_checkpoint(
            queries,
            ctx,
            config_path=config_path,
            judge=judge,
        )

    outcomes: dict[str, GateOutcome] = {}

    for row in targets:
        outcome = decide_row(
            scans[row.key],
            texts[row.key],
            judgements.get(row.key),
            errors.get(row.key)
            or (None if ctx.use_llm else "--no-llm"),
        )

        if outcome is not None:
            outcomes[row.key] = outcome

    return outcomes
