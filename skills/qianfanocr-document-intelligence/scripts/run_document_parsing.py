#!/usr/bin/env python3

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Optional, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent

DOCUMENT_PARSING_PROMPT = """You are an AI assistant specialized in converting document images (one or multiple pages extracted from a PDF) into Markdown with high fidelity.

Your task is to accurately convert all visible content from the images into Markdown, strictly following the rules below. Do not add explanations, comments, or inferred content.

1. Pages:
- The input may contain one or multiple page images.
- Preserve the exact page order as provided.
- If there are multiple pages, separate pages using the marker:
  --- Page N ---
  (N starts from 1)
- If there is only one page, do NOT output any page separator.

2. Text Recognition:
- Accurately convert all visible text.
- No guessing, inference, paraphrasing, or correction.
- Preserve the original document structure, including headings, paragraphs, lists, captions, and footnotes.
- Completely REMOVE all header and footer text. Do not output page numbers, running titles, or repeated marginal content.

3. Reading Order:
- Follow a top-to-bottom, left-to-right reading order.
- For multi-column layouts, fully read the left column before the right column.
- Do not reorder content for semantic or logical clarity.

4. Mathematical Formulas:
- Convert all mathematical expressions to LaTeX.
- Inline formulas must use $...$.
- Display (block) formulas must use:
  $$
  ...
  $$
- Preserve symbols, spacing, and structure exactly.
- Do not invent, simplify, normalize, or correct formulas.

5. Tables:
- Convert all tables to HTML format.
- Wrap each table with <table> and </table>.
- Preserve row and column order, merged cells (rowspan, colspan), and empty cells.
- Do not restructure or reinterpret tables.

6. Images:
- Do NOT describe image content.
- Preserve images using the exact format:
  ![label](<box>[[x1, y1, x2, y2]]</box>)
- Allowed labels: image, chart, seal.
- Completely REMOVE all header_image and footer_image elements.
- Do not introduce new labels.
- Do not remove or merge remaining image elements.

7. Unreadable or Missing Content:
- If text, symbols, or table cells are unreadable, preserve their position and leave the content empty.
- Do not guess or fill in missing information.

8. Output Requirements:
- Output Markdown only.
- Preserve original layout, spacing, and structure as closely as possible.
- Ensure clear separation between elements using line breaks.
- Do not include any explanations, metadata, or comments."""


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
        description="Run document parsing end-to-end and render image placeholders."
    )
    parser.add_argument("source", help="Source image path or PDF path")
    parser.add_argument("--page", type=int, default=1, help="1-based PDF page number to parse")
    parser.add_argument("--max-tokens", type=int, help="Optional max_tokens override")
    parser.add_argument(
        "--complex-layout",
        action="store_true",
        help="Use the complex-layout parameters from the skill reference",
    )
    parser.add_argument("--output-markdown", help="Optional final rendered markdown path")
    parser.add_argument("--output-dir", help="Optional rendered assets directory")
    parser.add_argument("--raw-markdown", help="Optional raw markdown output path")
    parser.add_argument("--log-file", help="Optional shared JSONL log file")
    parser.add_argument(
        "--no-render-overlay",
        action="store_true",
        help="Disable overlay image generation during markdown rendering",
    )
    return parser.parse_args(argv)


def resolve_source(source_value: str) -> Path:
    source = Path(source_value).expanduser().resolve()
    if not source.is_file():
        raise RunnerError(f"source file not found: {source}")
    return source


def derive_paths(source: Path, args: argparse.Namespace) -> Tuple[Path, Path, Path]:
    final_markdown = (
        Path(args.output_markdown).expanduser().resolve()
        if args.output_markdown
        else source.parent / f"{source.stem}.md"
    )
    raw_markdown = (
        Path(args.raw_markdown).expanduser().resolve()
        if args.raw_markdown
        else source.parent / f"{source.stem}.raw.md"
    )
    assets_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else source.parent / f"{source.stem}.assets"
    )
    return final_markdown, raw_markdown, assets_dir


def resolve_page_image(source: Path, page: int, log_file: Optional[str]) -> Path:
    if source.suffix.lower() != ".pdf":
        return source

    pdf_to_images = load_script_module("pdf_to_images")
    with tempfile.TemporaryDirectory(prefix="run_document_parsing_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        result = pdf_to_images.convert_one(
            pdftoppm_path=pdf_to_images.ensure_pdftoppm(),
            source=str(source),
            output_root=tmpdir_path,
            image_format="png",
            dpi=200,
            first_page=page,
            last_page=page,
            overwrite=True,
            scratch_dir=tmpdir_path / "scratch",
        )
        images = result.get("images", [])
        if not images:
            raise RunnerError(f"no page image generated for page {page}")
        page_image = Path(images[0])
        persistent_dir = source.parent / f"{source.stem}.pages"
        persistent_dir.mkdir(parents=True, exist_ok=True)
        persistent_path = persistent_dir / page_image.name
        persistent_path.write_bytes(page_image.read_bytes())
        if log_file:
            qianfan_cli = load_script_module("qianfan_ocr_cli")
            qianfan_cli.append_log(
                log_file,
                {
                    "script": "run_document_parsing",
                    "status": "pdf_page_prepared",
                    "source": str(source),
                    "page": page,
                    "page_image": str(persistent_path),
                },
            )
        return persistent_path


def build_cli_args(image_path: Path, args: argparse.Namespace):
    qianfan_cli = load_script_module("qianfan_ocr_cli")
    cli_argv = [
        DOCUMENT_PARSING_PROMPT,
        "--image",
        str(image_path),
    ]
    if args.max_tokens is not None:
        cli_argv.extend(["--max-tokens", str(args.max_tokens)])
    if args.complex_layout:
        cli_argv.extend(["--min-dynamic-patch", "8", "--max-dynamic-patch", "24"])
    if args.log_file:
        cli_argv.extend(["--log-file", args.log_file])
    return qianfan_cli, qianfan_cli.parse_args(cli_argv)


def run_document_parsing(source: Path, args: argparse.Namespace) -> Tuple[Path, Path, Path]:
    qianfan_cli = None
    try:
        image_path = resolve_page_image(source, args.page, args.log_file)
        final_markdown, raw_markdown, assets_dir = derive_paths(source, args)
        qianfan_cli, cli_args = build_cli_args(image_path, args)
        qianfan_cli.append_log(
            args.log_file,
            {
                "script": "run_document_parsing",
                "status": "started",
                "source": str(source),
                "page_image": str(image_path),
                "complex_layout": args.complex_layout,
            },
        )

        resp = qianfan_cli.request_chat(cli_args)
        try:
            raw_output = qianfan_cli.render_output(resp, cli_args)
        finally:
            resp.close()

        raw_markdown.parent.mkdir(parents=True, exist_ok=True)
        raw_markdown.write_text(raw_output, encoding="utf-8")

        render_doc_markdown = load_script_module("render_doc_markdown")
        render_args = render_doc_markdown.parse_args(
            [
                str(raw_markdown),
                "--image",
                str(image_path),
                "--source-path",
                str(source),
                "--output-markdown",
                str(final_markdown),
                "--output-dir",
                str(assets_dir),
                *([] if args.log_file is None else ["--log-file", args.log_file]),
                *([] if not args.no_render_overlay else ["--no-render-overlay"]),
            ]
        )
        markdown = render_doc_markdown.load_markdown(render_args.markdown)
        page_lookup = render_doc_markdown.build_page_lookup(render_args)
        source_path = render_doc_markdown.resolve_source_path(render_args, page_lookup)
        output_dir, output_markdown, relative_base = render_doc_markdown.resolve_output_paths(
            render_args,
            source_path,
        )
        rendered = render_doc_markdown.render_markdown(
            markdown=markdown,
            page_lookup=page_lookup,
            output_dir=output_dir,
            prefix=render_args.prefix,
            path_mode=render_args.path_mode,
            relative_base=relative_base,
            render_overlay=render_args.render_overlay,
        )
        if output_markdown is None:
            raise RunnerError("render step did not resolve an output markdown path")
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.write_text(rendered, encoding="utf-8")

        qianfan_cli.append_log(
            args.log_file,
            {
                "script": "run_document_parsing",
                "status": "succeeded",
                "source": str(source),
                "raw_markdown": str(raw_markdown),
                "final_markdown": str(output_markdown),
                "assets_dir": str(output_dir),
            },
        )
        return output_markdown, raw_markdown, output_dir
    except Exception as exc:
        if qianfan_cli is not None:
            qianfan_cli.append_log(
                args.log_file,
                {
                    "script": "run_document_parsing",
                    "status": "failed",
                    "source": str(source),
                    "error": str(exc),
                },
            )
        raise


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        source = resolve_source(args.source)
        final_markdown, raw_markdown, assets_dir = run_document_parsing(source, args)
        payload = {
            "source": str(source),
            "final_markdown": str(final_markdown),
            "raw_markdown": str(raw_markdown),
            "assets_dir": str(assets_dir),
        }
        json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
