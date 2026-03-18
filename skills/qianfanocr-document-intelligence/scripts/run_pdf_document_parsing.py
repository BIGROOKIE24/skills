#!/usr/bin/env python3

import argparse
import concurrent.futures
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import List, Optional, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent


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


def parse_pages_spec(value: str) -> Optional[Tuple[int, int]]:
    cleaned = value.strip().lower()
    if cleaned == "all":
        return None
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", cleaned)
    if not match:
        raise argparse.ArgumentTypeError("pages must be 'all', 'N', or 'N-M'")
    first = int(match.group(1))
    last = int(match.group(2) or first)
    if first <= 0 or last <= 0:
        raise argparse.ArgumentTypeError("page values must be greater than 0")
    if first > last:
        raise argparse.ArgumentTypeError("page range start cannot be greater than end")
    return first, last


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer value: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run document parsing for a PDF and export combined markdown, per-page markdown, and shared assets."
    )
    parser.add_argument("source", help="Source PDF path")
    parser.add_argument(
        "--pages",
        default="all",
        help="Pages to parse: all, N, or N-M",
    )
    parser.add_argument("--max-tokens", type=int, help="Optional max_tokens override")
    parser.add_argument(
        "--complex-layout",
        action="store_true",
        help="Use the complex-layout parameters from the skill reference",
    )
    parser.add_argument(
        "--request-mode",
        choices=["batch", "joint"],
        default="batch",
        help="batch: one request per page; joint: one request for all selected pages",
    )
    parser.add_argument("--output-markdown", help="Optional combined markdown output path")
    parser.add_argument("--output-dir", help="Optional shared assets output directory")
    parser.add_argument("--pages-dir", help="Optional per-page markdown output directory")
    parser.add_argument(
        "--concurrency",
        type=positive_int,
        default=1,
        help="Number of pages to parse concurrently. Default: 1",
    )
    parser.add_argument("--log-file", help="Optional shared JSONL log file")
    parser.add_argument(
        "--no-render-overlay",
        action="store_true",
        help="Disable overlay image generation during markdown rendering",
    )
    args = parser.parse_args(argv)
    args.pages = parse_pages_spec(args.pages)
    return args


def resolve_pdf(source_value: str) -> Path:
    source = Path(source_value).expanduser().resolve()
    if not source.is_file():
        raise RunnerError(f"source file not found: {source}")
    if source.suffix.lower() != ".pdf":
        raise RunnerError(f"source is not a PDF: {source}")
    return source


def derive_paths(source: Path, args: argparse.Namespace) -> Tuple[Path, Path, Path, Optional[int]]:
    single_page = args.pages[0] if args.pages is not None and args.pages[0] == args.pages[1] else None
    default_stem = f"{source.stem}_page{single_page}" if single_page is not None else source.stem
    combined_markdown = (
        Path(args.output_markdown).expanduser().resolve()
        if args.output_markdown
        else source.parent / f"{default_stem}.md"
    )
    assets_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else source.parent / f"{default_stem}.assets"
    )
    pages_dir = (
        Path(args.pages_dir).expanduser().resolve()
        if args.pages_dir
        else source.parent / f"{source.stem}.pages"
    )
    return combined_markdown, assets_dir, pages_dir, single_page


def convert_pages(source: Path, pages: Optional[Tuple[int, int]], log_file: Optional[str]) -> List[Tuple[int, Path]]:
    pdf_to_images = load_script_module("pdf_to_images")
    qianfan_cli = load_script_module("qianfan_ocr_cli")
    page_images_dir = source.parent / f"{source.stem}.pages"
    page_images_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="run_pdf_document_parsing_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        first_page = None if pages is None else pages[0]
        last_page = None if pages is None else pages[1]
        result = pdf_to_images.convert_one(
            pdftoppm_path=pdf_to_images.ensure_pdftoppm(),
            source=str(source),
            output_root=tmpdir_path,
            image_format="png",
            dpi=200,
            first_page=first_page,
            last_page=last_page,
            overwrite=True,
            scratch_dir=tmpdir_path / "scratch",
        )
        images = [Path(value) for value in result.get("images", [])]
        if not images:
            raise RunnerError("no page images were generated")
        copied = []
        for image in images:
            copied_path = page_images_dir / image.name
            shutil.copyfile(image, copied_path)
            page_match = re.search(r"-(\d+)\.png$", copied_path.name)
            if page_match is None:
                raise RunnerError(f"failed to infer page number from image name: {copied_path.name}")
            page_number = int(page_match.group(1))
            copied.append((page_number, copied_path))
            qianfan_cli.append_log(
                log_file,
                {
                    "script": "run_pdf_document_parsing",
                    "status": "pdf_page_prepared",
                    "source": str(source),
                    "page": page_number,
                    "page_image": str(copied_path),
                },
            )
        return copied


def render_one_page(
    source: Path,
    page_number: int,
    page_image: Path,
    page_markdown: Path,
    assets_dir: Path,
    max_tokens: Optional[int],
    complex_layout: bool,
    log_file: Optional[str],
    render_overlay: bool,
) -> str:
    run_document_parsing = load_script_module("run_document_parsing")
    qianfan_cli, cli_args = run_document_parsing.build_cli_args(
        page_image,
        argparse.Namespace(max_tokens=max_tokens, complex_layout=complex_layout, log_file=log_file),
    )
    qianfan_cli.append_log(
        log_file,
        {
            "script": "run_pdf_document_parsing",
            "status": "started_page",
            "source": str(source),
            "page": page_number,
            "page_image": str(page_image),
        },
    )

    resp = qianfan_cli.request_chat(cli_args)
    try:
        raw_output = qianfan_cli.render_output(resp, cli_args)
    finally:
        resp.close()

    render_doc_markdown = load_script_module("render_doc_markdown")
    with tempfile.TemporaryDirectory(prefix="run_pdf_document_parsing_render_") as tmpdir:
        raw_markdown = Path(tmpdir) / f"p{page_number:03d}.raw.md"
        raw_markdown.write_text(raw_output, encoding="utf-8")
        render_args = render_doc_markdown.parse_args(
            [
                str(raw_markdown),
                "--image",
                str(page_image),
                "--default-page-number",
                str(page_number),
                "--source-path",
                str(source),
                "--output-markdown",
                str(page_markdown),
                "--output-dir",
                str(assets_dir),
                *([] if log_file is None else ["--log-file", log_file]),
                *(["--no-render-overlay"] if not render_overlay else []),
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
            raise RunnerError(f"output markdown was not resolved for page {page_number}")
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.write_text(rendered, encoding="utf-8")

    qianfan_cli.append_log(
        log_file,
        {
            "script": "run_pdf_document_parsing",
            "status": "succeeded_page",
            "source": str(source),
            "page": page_number,
            "page_markdown": str(page_markdown),
        },
    )
    return rendered.strip()


def build_combined_markdown(page_contents: List[Tuple[int, str]]) -> str:
    if len(page_contents) == 1:
        return page_contents[0][1].rstrip() + "\n"
    parts = []
    for page_number, content in page_contents:
        parts.append(f"--- Page {page_number} ---\n\n{content.rstrip()}")
    return "\n\n".join(parts) + "\n"


def build_joint_cli_args(page_images: List[Path], args: argparse.Namespace):
    run_document_parsing = load_script_module("run_document_parsing")
    qianfan_cli = load_script_module("qianfan_ocr_cli")
    cli_argv = [run_document_parsing.DOCUMENT_PARSING_PROMPT]
    if args.max_tokens is not None:
        cli_argv.extend(["--max-tokens", str(args.max_tokens)])
    for image_path in page_images:
        cli_argv.extend(["--image", str(image_path)])
    if args.complex_layout:
        cli_argv.extend(["--min-dynamic-patch", "8", "--max-dynamic-patch", "24"])
    if args.log_file:
        cli_argv.extend(["--log-file", args.log_file])
    return qianfan_cli, qianfan_cli.parse_args(cli_argv)


def split_rendered_markdown(rendered: str) -> List[Tuple[int, str]]:
    pattern = re.compile(r"^\s*--- Page (?P<page>\d+) ---\s*$", re.MULTILINE)
    markers = list(pattern.finditer(rendered))
    if not markers:
        return []
    pieces: List[Tuple[int, str]] = []
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(rendered)
        pieces.append((int(marker.group("page")), rendered[start:end].strip() + "\n"))
    return pieces


def build_page_markdown_path(
    page_number: int,
    combined_markdown: Path,
    pages_dir: Path,
    single_page: Optional[int],
    custom_pages_dir: Optional[str],
) -> Path:
    if single_page is not None and not custom_pages_dir:
        return combined_markdown
    return pages_dir / f"p{page_number:03d}.md"


def render_page_task(
    source: Path,
    page_number: int,
    page_image: Path,
    combined_markdown: Path,
    pages_dir: Path,
    single_page: Optional[int],
    args: argparse.Namespace,
    assets_dir: Path,
) -> Tuple[int, Path, str]:
    page_markdown = build_page_markdown_path(
        page_number=page_number,
        combined_markdown=combined_markdown,
        pages_dir=pages_dir,
        single_page=single_page,
        custom_pages_dir=args.pages_dir,
    )
    rendered = render_one_page(
        source=source,
        page_number=page_number,
        page_image=page_image,
        page_markdown=page_markdown,
        assets_dir=assets_dir,
        max_tokens=args.max_tokens,
        complex_layout=args.complex_layout,
        log_file=args.log_file,
        render_overlay=not args.no_render_overlay,
    )
    return page_number, page_markdown, rendered


def run_pdf_document_parsing(args: argparse.Namespace) -> Tuple[Path, Path, Path, List[Path]]:
    source = resolve_pdf(args.source)
    combined_markdown, assets_dir, pages_dir, single_page = derive_paths(source, args)
    page_images = sorted(convert_pages(source, args.pages, args.log_file), key=lambda item: item[0])
    if single_page is None or args.pages_dir:
        pages_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    if args.request_mode == "joint":
        qianfan_cli, cli_args = build_joint_cli_args([image for _, image in page_images], args)
        qianfan_cli.append_log(
            args.log_file,
            {
                "script": "run_pdf_document_parsing",
                "status": "started_joint",
                "source": str(source),
                "page_count": len(page_images),
                "request_mode": "joint",
            },
        )
        resp = qianfan_cli.request_chat(cli_args)
        try:
            raw_output = qianfan_cli.render_output(resp, cli_args)
        finally:
            resp.close()

        render_doc_markdown = load_script_module("render_doc_markdown")
        render_argv = [
            "-",
            "--source-path",
            str(source),
            "--output-markdown",
            str(combined_markdown),
            "--output-dir",
            str(assets_dir),
        ]
        if len(page_images) == 1:
            render_argv.extend(["--image", str(page_images[0][1]), "--default-page-number", str(page_images[0][0])])
        else:
            for page_number, page_image in page_images:
                render_argv.extend(["--page-image", f"{page_number}={page_image}"])
        if args.log_file:
            render_argv.extend(["--log-file", args.log_file])
        if args.no_render_overlay:
            render_argv.append("--no-render-overlay")
        render_args = render_doc_markdown.parse_args(render_argv)
        page_lookup = render_doc_markdown.build_page_lookup(render_args)
        source_path = render_doc_markdown.resolve_source_path(render_args, page_lookup)
        output_dir, output_markdown, relative_base = render_doc_markdown.resolve_output_paths(
            render_args,
            source_path,
        )
        rendered_combined = render_doc_markdown.render_markdown(
            markdown=raw_output,
            page_lookup=page_lookup,
            output_dir=output_dir,
            prefix=render_args.prefix,
            path_mode=render_args.path_mode,
            relative_base=relative_base,
            render_overlay=render_args.render_overlay,
        )
        if output_markdown is None:
            raise RunnerError("joint mode did not resolve combined markdown output path")
        output_markdown.parent.mkdir(parents=True, exist_ok=True)
        output_markdown.write_text(rendered_combined, encoding="utf-8")

        split_pages = split_rendered_markdown(rendered_combined)
        page_outputs: List[Path] = []
        if single_page is not None and not args.pages_dir:
            page_outputs = [combined_markdown]
        elif split_pages:
            for page_number, content in split_pages:
                page_markdown = pages_dir / f"p{page_number:03d}.md"
                page_markdown.parent.mkdir(parents=True, exist_ok=True)
                page_markdown.write_text(content, encoding="utf-8")
                page_outputs.append(page_markdown)
        else:
            for page_number, _ in page_images:
                page_markdown = pages_dir / f"p{page_number:03d}.md"
                page_markdown.parent.mkdir(parents=True, exist_ok=True)
                page_markdown.write_text(rendered_combined, encoding="utf-8")
                page_outputs.append(page_markdown)

        qianfan_cli.append_log(
            args.log_file,
            {
                "script": "run_pdf_document_parsing",
                "status": "succeeded_joint",
                "source": str(source),
                "combined_markdown": str(combined_markdown),
                "assets_dir": str(assets_dir),
                "page_output_count": len(page_outputs),
            },
        )
        return source, combined_markdown, assets_dir, page_outputs

    page_outputs: List[Path] = []
    page_contents: List[Tuple[int, str]] = []
    if args.concurrency == 1 or len(page_images) <= 1:
        for page_number, page_image in page_images:
            _, page_markdown, rendered = render_page_task(
                source=source,
                page_number=page_number,
                page_image=page_image,
                combined_markdown=combined_markdown,
                pages_dir=pages_dir,
                single_page=single_page,
                args=args,
                assets_dir=assets_dir,
            )
            page_outputs.append(page_markdown)
            page_contents.append((page_number, rendered))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = [
                executor.submit(
                    render_page_task,
                    source,
                    page_number,
                    page_image,
                    combined_markdown,
                    pages_dir,
                    single_page,
                    args,
                    assets_dir,
                )
                for page_number, page_image in page_images
            ]
            for future in concurrent.futures.as_completed(futures):
                page_number, page_markdown, rendered = future.result()
                page_outputs.append(page_markdown)
                page_contents.append((page_number, rendered))

        page_outputs.sort(key=lambda path: path.name)
        page_contents.sort(key=lambda item: item[0])

    combined_markdown.parent.mkdir(parents=True, exist_ok=True)
    combined_markdown.write_text(build_combined_markdown(page_contents), encoding="utf-8")
    return source, combined_markdown, assets_dir, page_outputs


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        source, combined_markdown, assets_dir, page_outputs = run_pdf_document_parsing(args)
        payload = {
            "source": str(source),
            "combined_markdown": str(combined_markdown),
            "assets_dir": str(assets_dir),
            "page_markdowns": [str(path) for path in page_outputs],
        }
        json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
