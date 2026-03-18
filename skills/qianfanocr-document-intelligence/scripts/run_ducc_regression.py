#!/usr/bin/env python3

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence


@dataclass
class Case:
    case_id: str
    mode: str
    prompt: str
    expected: List[str]


class RegressionError(Exception):
    pass


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run agent-level regression cases through ducc and capture outputs."
    )
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).resolve().parent.parent / "tests" / "ducc_regression_cases.jsonl"),
        help="Path to regression cases JSONL",
    )
    parser.add_argument(
        "--ducc-bin",
        default="ducc",
        help="ducc executable name or absolute path",
    )
    parser.add_argument(
        "--ducc-args",
        default="",
        help="Extra arguments passed to ducc before the prompt, for example '--print'",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.cwd() / "ducc-regression-output"),
        help="Directory to store case outputs",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Optional case id filter; repeat to run multiple specific cases",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved commands and prompts without executing ducc",
    )
    return parser.parse_args(argv)


def load_cases(path: Path) -> List[Case]:
    cases = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            cases.append(
                Case(
                    case_id=payload["id"],
                    mode=payload["mode"],
                    prompt=payload["prompt"],
                    expected=list(payload.get("expected", [])),
                )
            )
    if not cases:
        raise RegressionError(f"no cases found in {path}")
    return cases


def filter_cases(cases: List[Case], selected_ids: List[str]) -> List[Case]:
    if not selected_ids:
        return cases
    wanted = set(selected_ids)
    filtered = [case for case in cases if case.case_id in wanted]
    missing = sorted(wanted - {case.case_id for case in filtered})
    if missing:
        raise RegressionError(f"unknown case ids: {', '.join(missing)}")
    return filtered


def build_command(ducc_bin: str, ducc_args: str, prompt: str) -> List[str]:
    command = [ducc_bin]
    if ducc_args.strip():
        command.extend(shlex.split(ducc_args))
    command.extend(["-p", prompt])
    return command


def run_case(case: Case, args: argparse.Namespace, output_root: Path) -> dict:
    case_dir = output_root / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "prompt.txt").write_text(case.prompt, encoding="utf-8")
    metadata = {
        "id": case.case_id,
        "mode": case.mode,
        "expected": case.expected,
    }
    (case_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    command = build_command(args.ducc_bin, args.ducc_args, case.prompt)
    (case_dir / "command.txt").write_text(" ".join(shlex.quote(part) for part in command) + "\n", encoding="utf-8")

    if args.dry_run:
        return {
            "id": case.case_id,
            "status": "dry_run",
            "command_file": str(case_dir / "command.txt"),
            "prompt_file": str(case_dir / "prompt.txt"),
        }

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )
    (case_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (case_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
    result = {
        "id": case.case_id,
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "output_dir": str(case_dir),
    }
    (case_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        cases_path = Path(args.cases).expanduser().resolve()
        output_root = Path(args.output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)

        cases = filter_cases(load_cases(cases_path), args.case_id)
        results = [run_case(case, args, output_root) for case in cases]
        json.dump({"results": results}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
