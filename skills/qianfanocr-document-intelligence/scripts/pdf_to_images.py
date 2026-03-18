#!/usr/bin/env python3

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen


class PdfToImagesError(Exception):
    pass


def append_log(log_file: Optional[str], payload: dict) -> None:
    if not log_file:
        return
    path = Path(log_file).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return cleaned or "document"


def download_pdf(url: str, scratch_dir: Path) -> Path:
    parsed = urlparse(url)
    filename = Path(parsed.path).name or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    target = scratch_dir / sanitize_name(filename)
    try:
        with urlopen(url) as response:
            target.write_bytes(response.read())
    except Exception as exc:
        raise PdfToImagesError(f"failed to download PDF: {url}: {exc}") from exc
    return target


def ensure_pdftoppm() -> str:
    tool = shutil.which("pdftoppm")
    if not tool:
        raise PdfToImagesError("pdftoppm is required but was not found in PATH")
    return tool


def resolve_input(value: str, scratch_dir: Path) -> Tuple[Path, str]:
    if is_url(value):
        local_path = download_pdf(value, scratch_dir)
        stem = Path(urlparse(value).path).stem or "document"
        return local_path, sanitize_name(stem)

    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise PdfToImagesError(f"PDF file not found: {value}")
    if path.suffix.lower() != ".pdf":
        raise PdfToImagesError(f"input is not a PDF: {value}")
    return path, sanitize_name(path.stem)


def build_command(
    pdftoppm_path: str,
    pdf_path: Path,
    output_prefix: Path,
    image_format: str,
    dpi: int,
    first_page: Optional[int],
    last_page: Optional[int],
) -> List[str]:
    command = [pdftoppm_path, f"-{image_format}", "-r", str(dpi)]
    if first_page is not None:
        command.extend(["-f", str(first_page)])
    if last_page is not None:
        command.extend(["-l", str(last_page)])
    command.extend([str(pdf_path), str(output_prefix)])
    return command


def collect_outputs(output_dir: Path, prefix_name: str, image_format: str) -> List[Path]:
    extension = ".jpg" if image_format == "jpeg" else f".{image_format}"
    files = sorted(output_dir.glob(f"{prefix_name}-*.{extension.lstrip('.')}"))
    return files


def convert_one(
    pdftoppm_path: str,
    source: str,
    output_root: Path,
    image_format: str,
    dpi: int,
    first_page: Optional[int],
    last_page: Optional[int],
    overwrite: bool,
    scratch_dir: Path,
) -> dict:
    pdf_path, base_name = resolve_input(source, scratch_dir)
    target_dir = output_root / base_name
    if target_dir.exists():
        if not overwrite:
            raise PdfToImagesError(f"output directory already exists: {target_dir}")
    else:
        target_dir.mkdir(parents=True, exist_ok=True)

    output_prefix = target_dir / base_name
    command = build_command(
        pdftoppm_path,
        pdf_path,
        output_prefix,
        image_format,
        dpi,
        first_page,
        last_page,
    )

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise PdfToImagesError(exc.stderr.strip() or f"pdftoppm failed for {source}") from exc

    images = collect_outputs(target_dir, base_name, image_format)
    if not images:
        raise PdfToImagesError(f"no images were generated for {source}")

    return {
        "source": source,
        "pdf_path": str(pdf_path),
        "output_dir": str(target_dir),
        "images": [str(path) for path in images],
        "page_count": len(images),
        "format": image_format,
        "dpi": dpi,
    }


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def parse_pages_range(value: str) -> Tuple[int, int]:
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", value.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"invalid --pages value: {value}")
    first = int(match.group(1))
    last = int(match.group(2) or first)
    if first <= 0 or last <= 0:
        raise argparse.ArgumentTypeError("page values must be greater than 0")
    if first > last:
        raise argparse.ArgumentTypeError("--pages start cannot be greater than end")
    return first, last


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert one or more PDF files or URLs into per-page images."
    )
    parser.add_argument("inputs", nargs="+", help="PDF file paths or PDF URLs")
    parser.add_argument("--output-dir", required=True, help="Directory to place converted images")
    parser.add_argument("--format", choices=["png", "jpeg"], default="png")
    parser.add_argument("--dpi", type=positive_int, default=200)
    parser.add_argument(
        "--pages",
        type=parse_pages_range,
        help="Optional page selection in the form N or N-M; maps to --first-page/--last-page",
    )
    parser.add_argument("--first-page", type=positive_int)
    parser.add_argument("--last-page", type=positive_int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--manifest", help="Optional JSON manifest output path")
    parser.add_argument("--log-file", help="Optional JSONL log file for invocation records")
    args = parser.parse_args(argv)
    if args.pages is not None:
        if args.first_page is not None or args.last_page is not None:
            parser.error("--pages cannot be used together with --first-page or --last-page")
        args.first_page, args.last_page = args.pages
    delattr(args, "pages")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = None
    try:
        args = parse_args(argv)
        append_log(
            args.log_file,
            {
                "script": "pdf_to_images",
                "status": "started",
                "inputs": list(args.inputs),
                "format": args.format,
                "dpi": args.dpi,
                "first_page": args.first_page,
                "last_page": args.last_page,
            },
        )
        if args.first_page and args.last_page and args.first_page > args.last_page:
            raise PdfToImagesError("--first-page cannot be greater than --last-page")

        pdftoppm_path = ensure_pdftoppm()
        output_root = Path(args.output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)

        results = []
        with tempfile.TemporaryDirectory(prefix="pdf_to_images_") as tmpdir:
            scratch_dir = Path(tmpdir)
            for source in args.inputs:
                result = convert_one(
                    pdftoppm_path=pdftoppm_path,
                    source=source,
                    output_root=output_root,
                    image_format=args.format,
                    dpi=args.dpi,
                    first_page=args.first_page,
                    last_page=args.last_page,
                    overwrite=args.overwrite,
                    scratch_dir=scratch_dir,
                )
                results.append(result)

        payload = {"documents": results}
        if args.manifest:
            manifest_path = Path(args.manifest).expanduser().resolve()
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n")

        json.dump(payload, sys.stdout, ensure_ascii=True, indent=2)
        sys.stdout.write("\n")
        append_log(
            args.log_file,
            {
                "script": "pdf_to_images",
                "status": "succeeded",
                "document_count": len(results),
            },
        )
        return 0
    except PdfToImagesError as exc:
        append_log(
            getattr(args, "log_file", None),
            {
                "script": "pdf_to_images",
                "status": "failed",
                "error": str(exc),
            },
        )
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PdfToImagesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
