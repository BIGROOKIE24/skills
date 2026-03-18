#!/usr/bin/env python3

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent

LAYOUT_ANALYSIS_PROMPT = """Extract all layout elements from this image.
Output in JSON format. Each element must include:
1.  `bbox`: `[x1, y1, x2, y2]`
2.  `category`: One of ['abstract', 'algorithm', 'aside_text', 'chart', 'content', 'display_formula', 'inline_formula', 'doc_title', 'figure_title', 'footer', 'footer_image', 'footnote', 'formula_number', 'header', 'header_image', 'image', 'number', 'paragraph_title', 'reference', 'reference_content', 'seal', 'table', 'text', 'vertical_text', 'vision_footnote']

**Important**: Do not include any extracted text in the output."""


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
        description="Run layout analysis and export layout JSON plus an overlay image."
    )
    parser.add_argument("source", help="Source image path or PDF path")
    parser.add_argument("--page", type=int, default=1, help="1-based PDF page number to analyze")
    parser.add_argument("--max-tokens", type=int, help="Optional max_tokens override")
    parser.add_argument("--layout-json", help="Optional layout json output path")
    parser.add_argument("--layout-overlay", help="Optional layout overlay image path")
    parser.add_argument("--log-file", help="Optional shared JSONL log file")
    return parser.parse_args(argv)


def derive_output_paths(source: Path, page: int, args: argparse.Namespace) -> Tuple[Path, Path]:
    page_suffix = f"_p{page:03d}" if source.suffix.lower() == ".pdf" else ""
    stem = f"{source.stem}{page_suffix}_layout"
    layout_json = (
        Path(args.layout_json).expanduser().resolve()
        if args.layout_json
        else source.parent / f"{stem}.json"
    )
    layout_overlay = (
        Path(args.layout_overlay).expanduser().resolve()
        if args.layout_overlay
        else source.parent / f"{stem}_overlay.png"
    )
    return layout_json, layout_overlay


def strip_json_fence(raw_output: str) -> str:
    text = raw_output.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text


def parse_bbox_value(bbox_raw) -> list[int]:
    if isinstance(bbox_raw, str):
        values = [int(x) for x in re.findall(r"\d+", re.sub(r"<COORD_(\d+)>", r"\1", bbox_raw))]
    else:
        values = [int(v) for v in bbox_raw]
    if len(values) != 4:
        raise RunnerError(f"invalid bbox value: {bbox_raw!r}")
    return values


def parse_layout_output(raw_output: str):
    cleaned = strip_json_fence(re.sub(r"<COORD_(\d+)>", r"\1", raw_output))
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise RunnerError("layout analysis output is not a JSON array")
    parsed = []
    for index, elem in enumerate(data):
        if not isinstance(elem, dict):
            raise RunnerError(f"layout element at index {index} is not an object: {elem!r}")
        if "bbox" not in elem or "category" not in elem:
            raise RunnerError(f"layout element at index {index} missing bbox/category: {elem!r}")
        bbox = parse_bbox_value(elem["bbox"])
        parsed.append({"bbox": bbox, "category": elem["category"]})
    return parsed


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        run_document_parsing = load_script_module("run_document_parsing")
        qianfan_cli = load_script_module("qianfan_ocr_cli")
        render_doc_markdown = load_script_module("render_doc_markdown")

        source = run_document_parsing.resolve_source(args.source)
        page_image = run_document_parsing.resolve_page_image(source, args.page, args.log_file)
        layout_json, layout_overlay = derive_output_paths(source, args.page, args)

        qianfan_cli.append_log(
            args.log_file,
            {
                "script": "run_layout_analysis",
                "status": "started",
                "source": str(source),
                "page_image": str(page_image),
            },
        )

        cli_args = qianfan_cli.parse_args(
            [
                LAYOUT_ANALYSIS_PROMPT,
                "--image",
                str(page_image),
                *([] if args.log_file is None else ["--log-file", args.log_file]),
                *(["--max-tokens", str(args.max_tokens)] if args.max_tokens is not None else []),
            ]
        )
        resp = qianfan_cli.request_chat(cli_args)
        try:
            payload = qianfan_cli.load_json(resp)
        finally:
            resp.close()
        raw_content = qianfan_cli.parse_response_content(payload)
        layout_json.parent.mkdir(parents=True, exist_ok=True)
        (layout_json.with_suffix(".raw.txt")).write_text(raw_content, encoding="utf-8")
        layout_entries = parse_layout_output(raw_content)

        layout_json.write_text(json.dumps(layout_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        boxes = []
        with ImageProxy(page_image) as image_proxy:
            width, height = image_proxy.size
            for item in layout_entries:
                pixel_box = render_doc_markdown.norm_to_pixels(tuple(item["bbox"]), width, height)
                boxes.append((item["category"], pixel_box))
        render_doc_markdown.save_overlay_image(page_image, boxes, layout_overlay)

        qianfan_cli.append_log(
            args.log_file,
            {
                "script": "run_layout_analysis",
                "status": "succeeded",
                "layout_json": str(layout_json),
                "layout_overlay": str(layout_overlay),
                "layout_count": len(layout_entries),
            },
        )

        json.dump(
            {
                "source": str(source),
                "layout_json": str(layout_json),
                "layout_overlay": str(layout_overlay),
                "layout_count": len(layout_entries),
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


class ImageProxy:
    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path
        self.image = None

    def __enter__(self):
        from PIL import Image

        self.image = Image.open(self.image_path)
        return self.image

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.image is not None:
            self.image.close()


if __name__ == "__main__":
    raise SystemExit(main())
