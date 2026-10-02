"""Gate — 파트너 위젯 당사(Samsung 전체) 무관 게시물 (태스크 1, 1차).

대상: 'Raw Data_원문' 시트 중 config/partner_scope.yaml의 widgets 접두어에 맞는 행(3. Partner ...).

판정 (config/partner_scope.yaml 머리말과 같은 흐름)
    당사 키워드 히트                           -> KEEP (규칙만 기록, 감사용)
    키워드 없음 + 본문이 너무 짧음              -> FLAG
    키워드 없음 + 본문 있음 + llm_drop_channels 밖(IG/YT/TT) -> FLAG (LLM 호출 없음)
    키워드 없음 + 본문 있음 + llm_drop_channels 안(X)         -> Gemini 텍스트 판정
        UNRELATED_TO_SAMSUNG + 코드 검증 통과   -> DROP
        그 외 / Gemini 실패 / --no-llm         -> FLAG

DROP은 (1) 키워드 히트 없음, (2) Gemini가 UNRELATED_TO_SAMSUNG, (3) Gemini가 인용한 근거가
원문에 실제로 있음, (4) Gemini가 당사 신호를 하나도 찾지 못함 — 네 가지가 모두 맞아야만 한다.
Gemini confidence 숫자는 판정에 쓰지 않는다.
"""

from __future__ import annotations

import json
import re
import sys
import time
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

from .schema import RAW_SHEET_ORIGINAL, GateContext, GateOutcome, RawRow, Verdict
from .scope_gate import (
    _CONTROL_CHAR_RE,
    DROP_CONSENSUS_CALLS,
    MAX_CLEAN_ATTEMPTS,
    compile_term,
    evidence_in_text,
    normalize_text,
    reason_is_garbled,
    run_judgements,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PARTNER_CONFIG_PATH = BASE_DIR / "config" / "partner_scope.yaml"
DEFAULT_PARTNER_PROMPT_PATH = BASE_DIR / "prompts" / "qc_partner_system_prompt.txt"

CHECKPOINT_TAG = "qc_partner"
CHECKPOINT_EXTRA_KEY = "partner_checkpoint_path"

WIDGET_FIELD = "source_widget"
CHANNEL_FIELD = "snType column"
TEXT_FIELD = "Conversation Stream"
ACCOUNT_FIELDS = ("User Name", "Author Screen Name", "Sender Screen Name")
BIO_FIELD = "Sender Bio"
MEDIA_FIELD = "Media URL"

RULE_KEYWORD = "PARTNER_SAMSUNG_KW"
RULE_NO_TEXT = "PARTNER_NO_TEXT"
RULE_MEDIA_CHANNEL = "PARTNER_MEDIA_CHANNEL"
RULE_UNRELATED_DROP = "PARTNER_UNRELATED"
RULE_LLM_RELATED = "PARTNER_LLM_RELATED"
RULE_LLM_UNCLEAR = "PARTNER_LLM_UNCLEAR"
RULE_DROP_UNVERIFIED = "PARTNER_DROP_UNVERIFIED"
RULE_LLM_UNAVAILABLE = "PARTNER_LLM_UNAVAILABLE"

VERDICT_UNRELATED = "UNRELATED_TO_SAMSUNG"
VERDICT_RELATED = "SAMSUNG_RELATED"
VERDICT_UNCLEAR = "UNCLEAR"
JUDGE_VERDICTS = (VERDICT_UNRELATED, VERDICT_RELATED, VERDICT_UNCLEAR)

JUDGE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(JUDGE_VERDICTS)},
        "evidence": {"type": "string"},
        "samsung_signals": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": [
        "verdict",
        "evidence",
        "samsung_signals",
        "reason",
        "confidence",
    ],
    "additionalProperties": False,
}

_URL_RE = re.compile(r"https?://\S+")


# ---------------------------------------------------------------------------
# 사전 로딩 / 매칭
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PartnerConfig:
    widgets: tuple[str, ...]
    llm_drop_channels: frozenset[str]
    min_text_chars: int
    patterns: tuple[tuple[str, re.Pattern[str]], ...]


def load_partner_config(path: Path) -> PartnerConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    widgets = data.get("widgets")
    terms = data.get("samsung_terms")
    min_chars = data.get("min_text_chars", 3)
    channels = data.get("llm_drop_channels")

    for name, value in (
        ("widgets", widgets),
        ("samsung_terms", terms),
        ("llm_drop_channels", channels),
    ):
        if not isinstance(value, list) or not value:
            raise ValueError(f"{path}: {name}는 비어 있지 않은 리스트여야 합니다.")

    if not isinstance(min_chars, int) or min_chars < 0:
        raise ValueError(f"{path}: min_text_chars는 0 이상의 정수여야 합니다.")

    compiled = []

    for term in terms:
        if not isinstance(term, str) or not term.strip():
            raise ValueError(f"{path}: 잘못된 용어 {term!r}")

        try:
            compiled.append((term, compile_term(term.strip())))
        except re.error as exc:
            raise ValueError(f"{path}: 정규식 오류 {term!r}: {exc}") from exc

    return PartnerConfig(
        widgets=tuple(str(w).strip() for w in widgets),
        llm_drop_channels=frozenset(str(c).strip().upper() for c in channels),
        min_text_chars=min_chars,
        patterns=tuple(compiled),
    )


def find_samsung_terms(text: str, config: PartnerConfig) -> list[str]:
    """겹치지 않게 찾은 매칭 문자열(대소문자 무시 중복 제거, 등장 순서)."""

    normalized = normalize_text(text)
    found: dict[str, str] = {}

    for _term, pattern in config.patterns:
        for match in pattern.finditer(normalized):
            found.setdefault(match.group(0).casefold(), match.group(0))

    return list(found.values())


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value)


def row_scan_text(row: RawRow) -> str:
    """키워드를 찾을 텍스트: 본문 + 계정명."""

    parts = [_cell_text(row.values.get(TEXT_FIELD))]
    parts.extend(_cell_text(row.values.get(f)) for f in ACCOUNT_FIELDS)

    return "\n".join(p for p in parts if p)


def _meaningful_chars(text: str) -> int:
    """URL과 공백을 뺀 글자 수."""

    return len("".join(_URL_RE.sub("", text).split()))


def llm_allowed(row: RawRow, config: PartnerConfig) -> bool:
    channel = _cell_text(row.values.get(CHANNEL_FIELD)).strip().upper()

    return channel in config.llm_drop_channels


def is_target(row: RawRow, config: PartnerConfig) -> bool:
    if row.sheet != RAW_SHEET_ORIGINAL:
        return False

    return _cell_text(row.values.get(WIDGET_FIELD)).strip().startswith(
        config.widgets
    )


# ---------------------------------------------------------------------------
# Gemini 판정
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PartnerQuery:
    key: str
    text: str
    account: str
    bio: str
    has_media: bool


@dataclass(frozen=True)
class Judgement:
    verdict: str
    evidence: str
    samsung_signals: tuple[str, ...]
    reason: str
    confidence: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "evidence": self.evidence,
            "samsung_signals": list(self.samsung_signals),
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
            samsung_signals=tuple(
                str(s) for s in data.get("samsung_signals") or []
            ),
            reason=str(data.get("reason") or ""),
            confidence=confidence if isinstance(confidence, int) else None,
        )


Judge = Callable[[PartnerQuery], Judgement]


def response_is_clean(judgement: Judgement, query: PartnerQuery) -> bool:
    """재호출 없이 쓸 수 있는 응답인지.

    제어문자가 섞이거나 reason이 깨졌거나, 당사 무관이라면서 근거가 원문에 없으면
    깨끗하지 않다. (당사 무관 외 판정의 근거는 쓰이지 않는다.)
    """

    if _CONTROL_CHAR_RE.search(judgement.evidence) or _CONTROL_CHAR_RE.search(
        judgement.reason
    ):
        return False

    if reason_is_garbled(judgement.reason):
        return False

    if judgement.verdict == VERDICT_UNRELATED:
        return _evidence_is_verified(judgement, query.text)[0]

    return True


def make_stable_judge(
    call: Judge,
    attempts: int = MAX_CLEAN_ATTEMPTS,
    consensus: int = DROP_CONSENSUS_CALLS,
) -> Judge:
    """한 번의 호출(call)을 일관성 있게 감싼다. scope_gate.make_stable_judge의 파트너판.

    1. 깨끗하지 않은 응답은 최대 attempts번까지 다시 부른다. 끝까지 깨끗하지 않으면
       마지막 응답을 그대로 돌려주고, 판정 규칙이 FLAG로 처리한다.
    2. 당사 무관(DROP 후보)은 consensus번 모두 당사 무관이고 깨끗해야 확정한다.
       하나라도 다르면 그 다른 응답을 돌려줘 FLAG가 되게 한다.
    """

    def obtain(query: PartnerQuery) -> Judgement:
        latest: Judgement | None = None

        for _ in range(max(1, attempts)):
            latest = call(query)

            if response_is_clean(latest, query):
                return latest

        assert latest is not None
        return latest

    def judge(query: PartnerQuery) -> Judgement:
        first = obtain(query)

        if first.verdict != VERDICT_UNRELATED or not response_is_clean(
            first, query
        ):
            return first

        for _ in range(max(1, consensus) - 1):
            other = obtain(query)

            if other.verdict != VERDICT_UNRELATED or not response_is_clean(
                other, query
            ):
                return other

        return first

    return judge


def build_user_message(query: PartnerQuery) -> str:
    return (
        "<post>\n"
        f"Account: {query.account or '(없음)'}\n"
        f"Account Bio: {query.bio or '(없음)'}\n"
        f"Media attached: {'yes (not visible to you)' if query.has_media else 'no'}\n\n"
        f"Text:\n{query.text}\n"
        "</post>"
    )


def build_gemini_judge(
    system_prompt_path: Path = DEFAULT_PARTNER_PROMPT_PATH,
) -> Judge:
    """기존 4단계의 create_genai_client / 모델 / 재시도 설정을 재사용한다.

    thinking_config는 지정하지 않는다(scope 게이트와 같은 이유: 판정이 약해질 수 있음).
    """

    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

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
    )

    def call(query: PartnerQuery) -> Judgement:
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

                # JSON 파싱 오류(JSONDecodeError는 ValueError)와 빈 응답도 일시적 깨짐이므로 재시도
                if attempt >= lap.MAX_RETRIES or not (
                    lap.is_retryable_api_error(exc)
                    or isinstance(exc, ValueError)
                ):
                    break

                time.sleep(min(2 ** (attempt - 1), 8))

        assert last_exc is not None
        raise last_exc

    return make_stable_judge(call)


def judge_with_checkpoint(
    queries: list[PartnerQuery],
    ctx: GateContext,
    config_path: Path,
    judge: Judge | None = None,
) -> tuple[dict[str, Judgement], dict[str, str]]:
    """성공한 판정을 3분마다 저장한다. 재실행하면 성공한 행은 다시 호출하지 않는다.

    체크포인트 정리는 최종 Excel 저장 뒤 run.py가 한다.
    """

    checkpoint_path = checkpoint_json_path(ctx.output_path, CHECKPOINT_TAG)
    fingerprint = source_fingerprint(
        ctx.input_path, config_path, DEFAULT_PARTNER_PROMPT_PATH
    )
    ctx.extra[CHECKPOINT_EXTRA_KEY] = checkpoint_path

    cached: dict[str, Judgement] = {}
    saved = load_checkpoint_json(checkpoint_path, fingerprint)

    if saved is not None:
        for key, data in saved.get("judgements", {}).items():
            try:
                cached[key] = Judgement.from_dict(data)
            except ValueError:
                continue

        print(f"[CHECKPOINT] partner 판정 {len(cached)}건 복원")

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


def _evidence_is_verified(
    judgement: Judgement, full_text: str
) -> tuple[bool, str]:
    if not judgement.evidence.strip():
        return False, "근거 인용이 비어 있음"

    if not evidence_in_text(judgement.evidence, full_text):
        return False, "근거 인용이 원문에서 확인되지 않음"

    if judgement.samsung_signals:
        return False, (
            "당사 신호가 언급됨: " + ", ".join(judgement.samsung_signals)
        )

    return True, ""


def decide_row(
    hits: list[str],
    text_chars: int,
    min_text_chars: int,
    full_text: str,
    judgement: Judgement | None,
    error: str | None,
) -> GateOutcome:
    if hits:
        return GateOutcome(
            Verdict.KEEP,
            RULE_KEYWORD,
            f"당사 키워드 있음: {', '.join(hits[:3])}",
        )

    if text_chars < min_text_chars:
        return GateOutcome(
            Verdict.FLAG,
            RULE_NO_TEXT,
            "본문이 거의 없어(이미지·영상 위주) 텍스트로 판단 불가",
        )

    if judgement is None:
        detail = error or "LLM 판정을 실행하지 않음"

        return GateOutcome(
            Verdict.FLAG,
            RULE_LLM_UNAVAILABLE,
            f"당사 키워드 없음, LLM 판정 없음({detail})",
        )

    confidence = judgement.confidence

    if judgement.verdict == VERDICT_RELATED:
        return GateOutcome(
            Verdict.FLAG,
            RULE_LLM_RELATED,
            f"당사 키워드는 없으나 LLM은 당사 관련으로 판정: {judgement.reason}",
            confidence,
        )

    if judgement.verdict == VERDICT_UNCLEAR:
        return GateOutcome(
            Verdict.FLAG,
            RULE_LLM_UNCLEAR,
            f"당사 키워드 없음, LLM 판단 불가: {judgement.reason}",
            confidence,
        )

    verified, why_not = _evidence_is_verified(judgement, full_text)

    if not verified:
        return GateOutcome(
            Verdict.FLAG,
            RULE_DROP_UNVERIFIED,
            f"LLM은 당사 무관이라 했으나 DROP 조건 미충족({why_not}): "
            f"{judgement.reason}",
            confidence,
        )

    return GateOutcome(
        Verdict.DROP,
        RULE_UNRELATED_DROP,
        f"당사 키워드 없음. LLM: {judgement.reason} / "
        f"근거: \"{judgement.evidence}\"",
        confidence,
    )


# ---------------------------------------------------------------------------
# 게이트 진입점
# ---------------------------------------------------------------------------


def run_partner_gate(
    rows: list[RawRow],
    ctx: GateContext,
    judge: Judge | None = None,
) -> dict[str, GateOutcome]:
    config_path = ctx.partner_config_path or DEFAULT_PARTNER_CONFIG_PATH
    config = load_partner_config(config_path)

    targets = [r for r in rows if is_target(r, config)]
    hits: dict[str, list[str]] = {}
    queries: list[PartnerQuery] = []

    for row in targets:
        row_hits = find_samsung_terms(row_scan_text(row), config)
        hits[row.key] = row_hits
        body = _cell_text(row.values.get(TEXT_FIELD))

        if (
            not row_hits
            and _meaningful_chars(body) >= config.min_text_chars
            and llm_allowed(row, config)
        ):
            queries.append(
                PartnerQuery(
                    key=row.key,
                    text=body,
                    account=_cell_text(
                        row.values.get("Sender Screen Name")
                        or row.values.get("User Name")
                    ),
                    bio=_cell_text(row.values.get(BIO_FIELD)),
                    has_media=bool(
                        _cell_text(row.values.get(MEDIA_FIELD)).strip()
                    ),
                )
            )

    judgements: dict[str, Judgement] = {}
    errors: dict[str, str] = {}

    if queries and ctx.use_llm:
        judgements, errors = judge_with_checkpoint(
            queries, ctx, config_path=config_path, judge=judge
        )

    outcomes: dict[str, GateOutcome] = {}

    for row in targets:
        body = _cell_text(row.values.get(TEXT_FIELD))

        if (
            not hits[row.key]
            and _meaningful_chars(body) >= config.min_text_chars
            and not llm_allowed(row, config)
        ):
            outcomes[row.key] = GateOutcome(
                Verdict.FLAG,
                RULE_MEDIA_CHANNEL,
                "당사 키워드 없음. 이 채널은 본문이 약하고 영상·이미지에 "
                "당사 제품이 나올 수 있어 LLM으로 DROP하지 않고 확인 필요",
            )
            continue

        outcomes[row.key] = decide_row(
            hits[row.key],
            _meaningful_chars(body),
            config.min_text_chars,
            body,
            judgements.get(row.key),
            errors.get(row.key) or (None if ctx.use_llm else "--no-llm"),
        )

    return outcomes
