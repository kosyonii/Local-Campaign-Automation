"""
Sprinklr API 병렬 호출 공용 도구.

buzz_volume_adaptor.py의 SlidingWindowRateLimiter + 429/403(Developer Over
Rate) 재시도 패턴을 위젯 병렬화(sprinklr_export_excel.py)에서도 재사용할 수
있도록 일반화해서 분리한 모듈이다. buzz_volume_adaptor.py 자체는 이 모듈을
사용하지 않으며 기존 코드도 수정하지 않는다.

RATE_LIMITER 인스턴스는 이 모듈이 고정값을 강제하지 않고, 호출자가 자신의
운영 정책(예: 시간당 호출 한도)에 맞춰 SlidingWindowRateLimiter를 직접
생성해서 fetch_sprinklr_data_with_retry()에 전달한다.
"""

from __future__ import annotations

import random
import threading
import time as time_module
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests


# =========================================================
# 재시도 튜닝 상수 (buzz_volume_adaptor.py와 동일한 값)
# =========================================================

# MAX_RETRIES는 최초 요청 이후 추가로 재시도하는 횟수다.
# 예: MAX_RETRIES=3이면 최대 4회 요청한다.
MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
RETRY_MAX_DELAY_SECONDS = 60.0

# Sprinklr가 403 Developer Over Rate 또는 429를 반환했는데
# Retry-After 헤더가 없을 때 모든 스레드가 함께 쉬는 최소/최대 시간이다.
RATE_LIMIT_BASE_COOLDOWN_SECONDS = 15.0
RATE_LIMIT_MAX_COOLDOWN_SECONDS = 300.0

REQUEST_CONNECT_TIMEOUT_SECONDS = 10
REQUEST_READ_TIMEOUT_SECONDS = 180

RETRYABLE_STATUS_CODES = frozenset({
    429,
    500,
    502,
    503,
    504,
})


class SprinklrRequestError(RuntimeError):
    """Sprinklr API 요청 실패 정보를 보존하는 예외."""

    def __init__(
        self,
        message: str,
        *,
        attempt_count: int,
        status_code: int | None = None,
        response_text: str | None = None,
    ) -> None:
        super().__init__(message)
        self.attempt_count = attempt_count
        self.status_code = status_code
        self.response_text = response_text


@dataclass(frozen=True)
class SprinklrFetchResult:
    response_json: dict[str, Any]
    attempt_count: int


# =========================================================
# 공유 취소 신호 / 출력 락 / thread-local session
# =========================================================
# 모듈 레벨 싱글턴이다. 이 모듈을 사용하는 스크립트는 프로세스당 한 번만
# 실행되므로(예: sprinklr_export_excel.py 단독 실행) 실행마다 새 프로세스와
# 함께 초기화된다. 같은 프로세스 안에서 여러 번 재사용하려면(예: 테스트)
# reset_stop_event()로 명시적으로 리셋한다.

_THREAD_LOCAL = threading.local()
_SESSION_REGISTRY: list[requests.Session] = []
_SESSION_REGISTRY_LOCK = threading.Lock()
_PRINT_LOCK = threading.Lock()
_STOP_EVENT = threading.Event()


def get_stop_event() -> threading.Event:
    """다른 모듈에서 협조적 취소 신호를 보내거나 확인할 때 사용한다."""
    return _STOP_EVENT


def reset_stop_event() -> None:
    """새 실행(또는 테스트 케이스) 시작 전 취소 신호를 초기화한다."""
    _STOP_EVENT.clear()


def safe_print(*values: Any) -> None:
    """병렬 작업 로그가 서로 섞이지 않도록 출력한다."""
    with _PRINT_LOCK:
        print(*values)


def get_thread_session() -> requests.Session:
    """각 작업 스레드에 전용 requests.Session을 하나씩 생성한다."""
    session = getattr(
        _THREAD_LOCAL,
        "sprinklr_session",
        None,
    )

    if session is None:
        session = requests.Session()

        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            max_retries=0,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        _THREAD_LOCAL.sprinklr_session = session

        with _SESSION_REGISTRY_LOCK:
            _SESSION_REGISTRY.append(session)

    return session


def close_registered_sessions() -> None:
    """현재 실행에서 생성된 스레드별 Session을 닫는다."""
    with _SESSION_REGISTRY_LOCK:
        sessions = list(_SESSION_REGISTRY)
        _SESSION_REGISTRY.clear()

    for session in sessions:
        session.close()


class SlidingWindowRateLimiter:
    """
    모든 작업 스레드가 공유하는 요청 시작 속도 제한기.

    max_calls=15, period_seconds=60이면 최근 60초 구간에
    최대 15개의 요청 시작만 허용한다.

    Sprinklr가 rate limit 응답을 반환하면 defer()로 모든 스레드에
    공통 cooldown을 적용한다. 한 스레드만 sleep하는 방식보다
    동시에 재시도하는 thundering herd를 줄일 수 있다.
    """

    def __init__(
        self,
        max_calls: int,
        period_seconds: float,
    ) -> None:
        if max_calls <= 0:
            raise ValueError(
                "max_calls는 1 이상이어야 합니다."
            )

        if period_seconds <= 0:
            raise ValueError(
                "period_seconds는 0보다 커야 합니다."
            )

        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._timestamps: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            sleep_seconds = 0.0

            with self._lock:
                current_time = time_module.monotonic()

                if current_time < self._blocked_until:
                    sleep_seconds = (
                        self._blocked_until - current_time
                    )
                else:
                    while (
                        self._timestamps
                        and current_time - self._timestamps[0]
                        >= self.period_seconds
                    ):
                        self._timestamps.popleft()

                    if len(self._timestamps) < self.max_calls:
                        self._timestamps.append(current_time)
                        return

                    sleep_seconds = max(
                        0.0,
                        self.period_seconds
                        - (current_time - self._timestamps[0]),
                    )

            if _STOP_EVENT.is_set():
                raise InterruptedError(
                    "사용자 중단 요청으로 API 호출 대기를 종료합니다."
                )

            if sleep_seconds > 0:
                _STOP_EVENT.wait(
                    timeout=min(sleep_seconds, 1.0)
                )

    def defer(self, cooldown_seconds: float) -> float:
        """모든 스레드의 다음 요청 가능 시각을 뒤로 미룬다."""
        if cooldown_seconds <= 0:
            return 0.0

        with self._lock:
            current_time = time_module.monotonic()
            requested_until = current_time + cooldown_seconds
            self._blocked_until = max(
                self._blocked_until,
                requested_until,
            )
            return max(
                0.0,
                self._blocked_until - current_time,
            )


# =========================================================
# Retry-After / backoff 계산
# =========================================================

def parse_retry_after_seconds(
    retry_after_header: str | None,
) -> float | None:
    """
    Retry-After의 두 표준 형식을 모두 지원한다.

    - 초 단위 숫자: "120"
    - HTTP 날짜: "Wed, 21 Oct 2015 07:28:00 GMT"
    """
    if not retry_after_header:
        return None

    normalized_header = retry_after_header.strip()

    try:
        seconds = float(normalized_header)
    except ValueError:
        seconds = None

    if seconds is not None:
        return max(0.0, seconds)

    try:
        retry_datetime = parsedate_to_datetime(
            normalized_header
        )
    except (TypeError, ValueError, OverflowError):
        return None

    if retry_datetime.tzinfo is None:
        retry_datetime = retry_datetime.replace(
            tzinfo=timezone.utc
        )

    now_utc = datetime.now(timezone.utc)
    return max(
        0.0,
        (retry_datetime.astimezone(timezone.utc) - now_utc).total_seconds(),
    )


def calculate_retry_delay(
    attempt_number: int,
    retry_after_header: str | None,
) -> float:
    """일반 재시도용 Retry-After 또는 exponential backoff+jitter."""
    retry_after_seconds = parse_retry_after_seconds(
        retry_after_header
    )

    if retry_after_seconds is not None:
        return min(
            retry_after_seconds,
            RETRY_MAX_DELAY_SECONDS,
        )

    exponential_delay = (
        RETRY_BASE_DELAY_SECONDS
        * (2 ** max(attempt_number - 1, 0))
    )
    jitter = random.uniform(0.0, 1.0)

    return min(
        exponential_delay + jitter,
        RETRY_MAX_DELAY_SECONDS,
    )


def calculate_rate_limit_delay(
    attempt_number: int,
    retry_after_header: str | None,
) -> float:
    """Rate limit 전용으로 더 보수적인 공통 cooldown을 계산한다."""
    retry_after_seconds = parse_retry_after_seconds(
        retry_after_header
    )

    if retry_after_seconds is not None:
        return min(
            retry_after_seconds,
            RATE_LIMIT_MAX_COOLDOWN_SECONDS,
        )

    exponential_delay = (
        RATE_LIMIT_BASE_COOLDOWN_SECONDS
        * (2 ** max(attempt_number - 1, 0))
    )
    jitter = random.uniform(0.0, 3.0)

    return min(
        exponential_delay + jitter,
        RATE_LIMIT_MAX_COOLDOWN_SECONDS,
    )


def is_developer_over_rate_response(
    response: requests.Response,
) -> bool:
    """Sprinklr 고유의 403 Developer Over Rate 응답인지 판별한다."""
    return (
        response.status_code == 403
        and "developer over rate" in response.text.casefold()
    )


def is_rate_limit_response(
    response: requests.Response,
) -> bool:
    return (
        response.status_code == 429
        or is_developer_over_rate_response(response)
    )


# =========================================================
# 재시도 + rate limit 포함 Sprinklr API 호출
# =========================================================

def fetch_sprinklr_data_with_retry(
    base_url: str,
    endpoint: str,
    api_key: str | None,
    access_token: str | None,
    payload: dict[str, Any],
    *,
    rate_limiter: SlidingWindowRateLimiter,
    request_label: str,
) -> SprinklrFetchResult:
    """
    Sprinklr Reporting API를 호출한다.

    자동 재시도 대상:
    - Timeout 및 네트워크 연결 오류
    - 429
    - 500, 502, 503, 504
    - 403 응답 중 본문이 "Developer Over Rate"인 경우

    일반적인 400, 401, 403 권한 오류는 즉시 실패 처리한다.
    Rate limit 응답은 개별 스레드만 쉬지 않고 rate_limiter에 공통
    cooldown을 적용하여 이 rate_limiter를 공유하는 모든 worker가
    함께 속도를 낮춘다.
    """
    if not api_key:
        raise ValueError(
            "API_KEY가 없습니다. "
            "SPRINKLR_API_KEY 환경변수를 확인하세요."
        )

    if not access_token:
        raise ValueError(
            "ACCESS_TOKEN이 없습니다. "
            "SPRINKLR_ACCESS_TOKEN 환경변수를 확인하세요."
        )

    if not isinstance(payload, dict):
        raise TypeError(
            "payload는 dict여야 합니다."
        )

    url = (
        f"{base_url.rstrip('/')}/"
        f"{endpoint.lstrip('/')}"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    session = get_thread_session()
    max_attempts = MAX_RETRIES + 1

    for attempt_number in range(1, max_attempts + 1):
        if _STOP_EVENT.is_set():
            raise SprinklrRequestError(
                "사용자 중단 요청으로 API 작업을 종료했습니다.",
                attempt_count=max(0, attempt_number - 1),
            )

        try:
            rate_limiter.acquire()

            response = session.post(
                url,
                headers=headers,
                json=payload,
                timeout=(
                    REQUEST_CONNECT_TIMEOUT_SECONDS,
                    REQUEST_READ_TIMEOUT_SECONDS,
                ),
            )

            response_text = response.text[:3000]
            rate_limit_error = is_rate_limit_response(response)
            retryable_http_error = (
                rate_limit_error
                or response.status_code in RETRYABLE_STATUS_CODES
            )

            if retryable_http_error:
                if rate_limit_error:
                    retry_delay = calculate_rate_limit_delay(
                        attempt_number=attempt_number,
                        retry_after_header=response.headers.get(
                            "Retry-After"
                        ),
                    )
                    effective_cooldown = rate_limiter.defer(
                        retry_delay
                    )
                    error_name = (
                        "Developer Over Rate"
                        if is_developer_over_rate_response(response)
                        else "Rate Limit"
                    )

                    safe_print(
                        f"[COOLDOWN] 공통 rate-limit cooldown: "
                        f"{request_label}, {error_name}, "
                        f"HTTP {response.status_code}, "
                        f"약 {effective_cooldown:.1f}초, "
                        f"시도 {attempt_number}/{max_attempts}"
                    )
                else:
                    retry_delay = calculate_retry_delay(
                        attempt_number=attempt_number,
                        retry_after_header=response.headers.get(
                            "Retry-After"
                        ),
                    )
                    safe_print(
                        f"[RETRY] 재시도 예정: {request_label}, "
                        f"HTTP {response.status_code}, "
                        f"{retry_delay:.1f}초 후 "
                        f"재시도 ({attempt_number}/{max_attempts})"
                    )

                if attempt_number < max_attempts:
                    if rate_limit_error:
                        # 다음 루프의 acquire()에서 이 rate_limiter를
                        # 공유하는 모든 worker가 공통 cooldown이 끝날
                        # 때까지 기다린다.
                        continue

                    if _STOP_EVENT.wait(timeout=retry_delay):
                        raise SprinklrRequestError(
                            "사용자 중단 요청으로 재시도 대기를 "
                            "종료했습니다.",
                            attempt_count=attempt_number,
                            status_code=response.status_code,
                            response_text=response_text,
                        )
                    continue

                error_description = (
                    "Sprinklr API rate limit 오류가"
                    if rate_limit_error
                    else "Sprinklr API 재시도 가능 HTTP 오류가"
                )
                raise SprinklrRequestError(
                    f"{error_description} 최대 시도 횟수까지 "
                    "계속 발생했습니다.\n"
                    f"status_code: {response.status_code}\n"
                    f"url: {url}\n"
                    f"response: {response_text}",
                    attempt_count=attempt_number,
                    status_code=response.status_code,
                    response_text=response_text,
                )

            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as exc:
                raise SprinklrRequestError(
                    "Sprinklr API가 재시도하지 않는 HTTP 오류를 "
                    "반환했습니다.\n"
                    f"status_code: {response.status_code}\n"
                    f"url: {url}\n"
                    f"response: {response_text}",
                    attempt_count=attempt_number,
                    status_code=response.status_code,
                    response_text=response_text,
                ) from exc

            try:
                response_json = response.json()
            except requests.exceptions.JSONDecodeError as exc:
                if attempt_number < max_attempts:
                    retry_delay = calculate_retry_delay(
                        attempt_number=attempt_number,
                        retry_after_header=None,
                    )
                    safe_print(
                        f"[RETRY] JSON 응답 재시도 예정: {request_label}, "
                        f"{retry_delay:.1f}초 후 "
                        f"재시도 ({attempt_number}/{max_attempts})"
                    )
                    if _STOP_EVENT.wait(timeout=retry_delay):
                        raise SprinklrRequestError(
                            "사용자 중단 요청으로 JSON 응답 "
                            "재시도 대기를 종료했습니다.",
                            attempt_count=attempt_number,
                            status_code=response.status_code,
                            response_text=response_text,
                        )
                    continue

                raise SprinklrRequestError(
                    "Sprinklr API 응답이 최대 시도 횟수까지 "
                    "JSON 형식이 아니었습니다.\n"
                    f"status_code: {response.status_code}\n"
                    f"response: {response_text}",
                    attempt_count=attempt_number,
                    status_code=response.status_code,
                    response_text=response_text,
                ) from exc

            if not isinstance(response_json, dict):
                raise SprinklrRequestError(
                    "Sprinklr API 응답의 최상위 구조는 "
                    "JSON object여야 합니다. "
                    f"실제 타입: {type(response_json).__name__}",
                    attempt_count=attempt_number,
                    status_code=response.status_code,
                    response_text=response_text,
                )

            return SprinklrFetchResult(
                response_json=response_json,
                attempt_count=attempt_number,
            )

        except requests.exceptions.Timeout as exc:
            if attempt_number < max_attempts:
                retry_delay = calculate_retry_delay(
                    attempt_number=attempt_number,
                    retry_after_header=None,
                )
                safe_print(
                    f"[RETRY] Timeout 재시도 예정: {request_label}, "
                    f"{retry_delay:.1f}초 후 "
                    f"재시도 ({attempt_number}/{max_attempts})"
                )
                if _STOP_EVENT.wait(timeout=retry_delay):
                    raise SprinklrRequestError(
                        "사용자 중단 요청으로 Timeout 재시도 "
                        "대기를 종료했습니다.",
                        attempt_count=attempt_number,
                    )
                continue

            raise SprinklrRequestError(
                "Sprinklr API 요청 시간이 최대 시도 횟수까지 "
                "초과되었습니다.\n"
                f"URL: {url}",
                attempt_count=attempt_number,
            ) from exc

        except requests.exceptions.ConnectionError as exc:
            if attempt_number < max_attempts:
                retry_delay = calculate_retry_delay(
                    attempt_number=attempt_number,
                    retry_after_header=None,
                )
                safe_print(
                    f"[RETRY] 연결 오류 재시도 예정: {request_label}, "
                    f"{retry_delay:.1f}초 후 "
                    f"재시도 ({attempt_number}/{max_attempts})"
                )
                if _STOP_EVENT.wait(timeout=retry_delay):
                    raise SprinklrRequestError(
                        "사용자 중단 요청으로 연결 오류 재시도 "
                        "대기를 종료했습니다.",
                        attempt_count=attempt_number,
                    )
                continue

            raise SprinklrRequestError(
                "Sprinklr API 서버 연결 오류가 최대 시도 횟수까지 "
                "발생했습니다.\n"
                f"URL: {url}",
                attempt_count=attempt_number,
            ) from exc

        except requests.exceptions.RequestException as exc:
            if attempt_number < max_attempts:
                retry_delay = calculate_retry_delay(
                    attempt_number=attempt_number,
                    retry_after_header=None,
                )
                safe_print(
                    f"[RETRY] 요청 오류 재시도 예정: {request_label}, "
                    f"{retry_delay:.1f}초 후 "
                    f"재시도 ({attempt_number}/{max_attempts})"
                )
                if _STOP_EVENT.wait(timeout=retry_delay):
                    raise SprinklrRequestError(
                        "사용자 중단 요청으로 요청 오류 재시도 "
                        "대기를 종료했습니다.",
                        attempt_count=attempt_number,
                    )
                continue

            raise SprinklrRequestError(
                "Sprinklr API 요청 오류가 최대 시도 횟수까지 "
                "발생했습니다.\n"
                f"URL: {url}",
                attempt_count=attempt_number,
            ) from exc

    raise RuntimeError(
        "Sprinklr API 재시도 루프가 예상하지 못한 상태로 종료되었습니다."
    )
