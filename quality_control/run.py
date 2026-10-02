"""QC 게이트 CLI.

    python -m quality_control.run INPUT.xlsx [-o OUTPUT.xlsx] [--gates scope] [--no-llm]

원본 시트는 그대로 두고 QC_Full / QC_Clean / QC_Dropped 시트를 추가한 새 파일을 만든다.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

from checkpoint_utils import remove_checkpoint

from .schema import (
    GateContext,
    GateOutcome,
    QCRecord,
    RawRow,
    Verdict,
    merge_outcomes,
)
from .follower_gate import run_follower_gate
from .scope_gate import run_scope_gate
from .workbook_io import load_input_workbook, read_raw_rows, write_qc_workbook

GateFn = Callable[[list[RawRow], GateContext], dict[str, GateOutcome]]

# Phase 2(partner), Phase 3(global)가 여기에 추가된다.
GATES: dict[str, GateFn] = {
    "scope": run_scope_gate,
    "follower": run_follower_gate,
}

OUTPUT_SUFFIX = "_qc"
DROP_PREVIEW_CHARS = 70


def default_output_path(input_path: Path) -> Path:
    stem = input_path.stem

    if stem.endswith(OUTPUT_SUFFIX):
        stem = stem[: -len(OUTPUT_SUFFIX)]

    return input_path.with_name(f"{stem}{OUTPUT_SUFFIX}.xlsx")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m quality_control.run",
        description="Sprinklr raw 수기 검수 자동화 (DROP / FLAG / KEEP)",
    )
    parser.add_argument("input", type=Path, help="1단계 raw Excel")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=f"출력 Excel (기본: <입력>{OUTPUT_SUFFIX}.xlsx). 입력과 같으면 거부",
    )
    parser.add_argument(
        "--gates",
        default=",".join(GATES),
        help=f"실행할 게이트, 쉼표 구분 (사용 가능: {', '.join(GATES)})",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Gemini를 호출하지 않는다. LLM이 필요한 행은 DROP 없이 FLAG",
    )
    parser.add_argument(
        "--workers", type=int, help="Gemini 병렬 호출 수 (기본: GEMINI_MAX_WORKERS)"
    )
    parser.add_argument(
        "--scope-config",
        type=Path,
        help="비모바일 scope 사전 YAML (기본: config/product_scope.yaml)",
    )
    parser.add_argument(
        "--follower-config",
        type=Path,
        help="팔로워 기준 YAML (기본: config/follower_rule.yaml)",
    )

    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    input_path: Path = args.input.resolve()

    if not input_path.is_file():
        print(f"입력 파일이 없습니다: {input_path}", file=sys.stderr)
        return 2

    output_path = (
        args.output.resolve()
        if args.output
        else default_output_path(input_path)
    )

    if output_path == input_path:
        print("출력 경로가 입력 파일과 같습니다. 원본은 덮어쓰지 않습니다.", file=sys.stderr)
        return 2

    gate_names = [g.strip() for g in args.gates.split(",") if g.strip()]
    unknown = [g for g in gate_names if g not in GATES]

    if unknown:
        print(f"알 수 없는 게이트: {', '.join(unknown)}", file=sys.stderr)
        return 2

    ctx = GateContext(
        input_path=input_path,
        output_path=output_path,
        use_llm=not args.no_llm,
        workers=args.workers,
        scope_config_path=args.scope_config,
        follower_config_path=args.follower_config,
    )

    workbook = load_input_workbook(input_path)
    rows, raw_columns = read_raw_rows(workbook)
    print(f"[QC] 입력 {len(rows)}행: {dict(Counter(r.sheet for r in rows))}")

    per_row: dict[str, list[GateOutcome]] = {}

    for name in gate_names:
        print(f"[QC] 게이트 실행: {name}")

        try:
            outcomes = GATES[name](rows, ctx)
        except (ImportError, RuntimeError, FileNotFoundError) as exc:
            print(
                f"[QC] 게이트 '{name}' 실패: {exc}\n"
                "     Gemini 없이 키워드만 돌리려면 --no-llm을 쓰세요.",
                file=sys.stderr,
            )
            return 3

        for key, outcome in outcomes.items():
            per_row.setdefault(key, []).append(outcome)

    records = {key: merge_outcomes(o) for key, o in per_row.items()}
    counts = write_qc_workbook(
        workbook, output_path, rows, raw_columns, records
    )

    checkpoint_path = ctx.extra.get("scope_checkpoint_path")
    if checkpoint_path is not None:
        remove_checkpoint(checkpoint_path)

    print_summary(rows, records, counts, output_path)
    return 0


def print_summary(
    rows: list[RawRow],
    records: dict[str, QCRecord],
    counts: dict[str, int],
    output_path: Path,
) -> None:
    verdicts = Counter(
        records[r.key].verdict.value if r.key in records else "KEEP"
        for r in rows
    )
    rules = Counter(
        rule
        for record in records.values()
        for rule in record.rule.split(" | ")
        if rule
    )

    print(f"\n[QC] 판정: {dict(verdicts)}")
    print(f"[QC] 규칙별: {dict(rules)}")
    print(f"[QC] 시트 행 수: {counts}")

    drops = [
        (r, records[r.key])
        for r in rows
        if r.key in records and records[r.key].verdict is Verdict.DROP
    ]

    if drops:
        print("\n[QC] DROP 목록 — 최종 수기 검수 때 한 번 훑어보세요")

        for row, record in drops:
            text = str(row.values.get("Conversation Stream") or "")
            preview = " ".join(text.split())[:DROP_PREVIEW_CHARS]
            print(f"  {row.key}  {preview}\n      -> {record.reason}")

    print(f"\n[QC] 저장 완료: {output_path}")


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
