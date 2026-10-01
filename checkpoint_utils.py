"""파이프라인 단계 공용 체크포인트 유틸.

- 3분(기본)마다 진행 상태를 JSON으로 저장한다.
- 임시 파일에 쓴 뒤 os.replace로 교체하므로, 저장 도중 프로세스가 죽어도
  기존 체크포인트는 손상되지 않는다.
- 입력 파일의 fingerprint(수정 시각 + 크기)를 함께 저장해, 입력이 바뀐 뒤에는
  옛 체크포인트를 무시하고 처음부터 시작한다.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

CHECKPOINT_INTERVAL_SECONDS = 180.0


def source_fingerprint(*paths: Path) -> str:
    """입력 파일들의 수정 시각과 크기로 fingerprint 문자열을 만든다."""

    parts: list[str] = []

    for path in paths:
        stat = Path(path).stat()
        parts.append(f"{stat.st_mtime_ns}:{stat.st_size}")

    return "|".join(parts)


def checkpoint_json_path(output_path: Path, tag: str) -> Path:
    output_path = Path(output_path)

    return output_path.with_name(
        f".{output_path.stem}.{tag}.checkpoint.json"
    )


def load_checkpoint_json(
    path: Path,
    expected_fingerprint: str,
) -> dict[str, Any] | None:
    """체크포인트를 읽는다. 없거나 fingerprint가 다르거나 깨졌으면 None."""

    path = Path(path)

    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[CHECKPOINT] 체크포인트를 읽지 못해 무시합니다: {exc}")
        return None

    if data.get("source_fingerprint") != expected_fingerprint:
        print(
            "[CHECKPOINT] 입력 파일이 바뀌었거나 fingerprint가 없는 "
            "체크포인트라 무시하고 처음부터 시작합니다."
        )
        return None

    return data


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path = Path(path)
    temp_path = path.with_name(path.name + ".tmp")

    temp_path.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temp_path, path)


def remove_checkpoint(path: Path) -> None:
    path = Path(path)

    for target in (path, path.with_name(path.name + ".tmp")):
        try:
            target.unlink()
        except FileNotFoundError:
            pass


class PeriodicCheckpoint:
    """interval_seconds가 지났을 때만 저장하는 스레드 안전 저장기."""

    def __init__(
        self,
        path: Path,
        fingerprint: str,
        interval_seconds: float = CHECKPOINT_INTERVAL_SECONDS,
    ) -> None:
        self.path = Path(path)
        self.fingerprint = fingerprint
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._last_saved = time.monotonic()

    def maybe_save(self, build_state, force: bool = False) -> bool:
        """build_state()는 JSON 직렬화 가능한 dict를 돌려주는 함수.

        저장 시점에만 호출되므로 평소에는 비용이 들지 않는다.
        """

        with self._lock:
            now = time.monotonic()

            if (
                not force
                and now - self._last_saved < self.interval_seconds
            ):
                return False

            state = dict(build_state())
            state["source_fingerprint"] = self.fingerprint
            atomic_write_json(self.path, state)
            self._last_saved = now

        print(f"[CHECKPOINT] 저장 완료: {self.path.name}")
        return True

    def cleanup(self) -> None:
        remove_checkpoint(self.path)
