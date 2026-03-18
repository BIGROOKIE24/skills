#!/usr/bin/env python3

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent

PROMPTS = {
    "text": "Please extract the text from the image.",
    "formula": "Please convert the formula in the image to LaTeX.",
    "table": "Please convert the table in the image to HTML.",
}


class RunnerError(Exception):
    pass


def load_script_module(name: str) -> ModuleType:
    path = SCRIPT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RunnerError(f"failed to load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run element recognition and save the result as a sibling markdown file."
    )
    parser.add_argument("source", help="Source image path or PDF path")
    parser.add_argument(
        "--element-type",
        choices=sorted(PROMPTS.keys()),
        default="text",
        help="Type of cropped element to recognize",
    )
    parser.add_argument("--max-tokens", type=int, help="Optional max_tokens override")
    parser.add_argument("--page", type=int, default=1, help="1-based PDF page number to analyze")
    parser.add_argument("--output-markdown", help="Optional markdown output path")
    parser.add_argument("--log-file", help="Optional shared JSONL log file")
    return parser.parse_args(argv)


def resolve_source(source_value: str) -> Path:
    source = Path(source_value).expanduser().resolve()
    if not source.is_file():
        raise RunnerError(f"source file not found: {source}")
    return source


def derive_output_path(source: Path, page: int, args: argparse.Namespace) -> Path:
    if args.output_markdown:
        return Path(args.output_markdown).expanduser().resolve()
    suffix = f"_p{page:03d}" if source.suffix.lower() == ".pdf" else ""
    return source.parent / f"{source.stem}{suffix}.md"


def build_cli_args(image_path: Path, prompt: str, args: argparse.Namespace):
    qianfan_cli = load_script_module("qianfan_ocr_cli")
    cli_argv = [
        prompt,
        "--image",
        str(image_path),
    ]
    if args.max_tokens is not None:
        cli_argv.extend(["--max-tokens", str(args.max_tokens)])
    if args.log_file:
        cli_argv.extend(["--log-file", args.log_file])
    return qianfan_cli, qianfan_cli.parse_args(cli_argv)


def run_element_recognition(args: argparse.Namespace) -> Tuple[Path, Path]:
    run_document_parsing = load_script_module("run_document_parsing")
    qianfan_cli = None
    source = resolve_source(args.source)
    image_path = run_document_parsing.resolve_page_image(source, args.page, args.log_file)
    output_markdown = derive_output_path(source, args.page, args)
    prompt = PROMPTS[args.element_type]

    qianfan_cli, cli_args = build_cli_args(image_path, prompt, args)
    qianfan_cli.append_log(
        args.log_file,
        {
            "script": "run_element_recognition",
            "status": "started",
            "source": str(source),
            "page_image": str(image_path),
            "element_type": args.element_type,
        },
    )

    resp = qianfan_cli.request_chat(cli_args)
    try:
        rendered = qianfan_cli.render_output(resp, cli_args)
    finally:
        resp.close()

    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.write_text(rendered, encoding="utf-8")

    qianfan_cli.append_log(
        args.log_file,
        {
            "script": "run_element_recognition",
            "status": "succeeded",
            "source": str(source),
            "output_markdown": str(output_markdown),
            "element_type": args.element_type,
        },
    )
    return source, output_markdown


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        source, output_markdown = run_element_recognition(args)
        json.dump(
            {
                "source": str(source),
                "output_markdown": str(output_markdown),
                "element_type": args.element_type,
            },
            sys.stdout,
            ensure_ascii=True,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
