#!/usr/bin/env python3

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Match, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont


IMAGE_PATTERN = re.compile(
    r"!\[(?P<label>[^\]]*)\]\(\[\[(?P<coords>[^\]]+)\]\]\)|"
    r"!\[(?P<label_box>[^\]]*)\]\(<box>\[\[(?P<box_coords>[^\]]+)\]\]</box>\)"
)
PAGE_MARKER_PATTERN = re.compile(r"^\s*--- Page (?P<page>\d+) ---\s*$", re.MULTILINE)
COORD_PATTERN = re.compile(r"(?:<COORD_(\d+)>|(\d+))")
# Align with the reference layout visualization color map.
DEFAULT_COLORS = {
    "abstract": "#FF6B6B",
    "algorithm": "#4ECDC4",
    "aside_text": "#45B7D1",
    "chart": "#96CEB4",
    "content": "#FFEAA7",
    "display_formula": "#DDA0DD",
    "doc_title": "#FF4757",
    "inline_formula": "#B33771",
    "figure_title": "#2ED573",
    "footer": "#A4B0BE",
    "footer_image": "#747D8C",
    "footnote": "#FECA57",
    "formula_number": "#FF9FF3",
    "header": "#54A0FF",
    "header_image": "#5F27CD",
    "image": "#FF6348",
    "number": "#1DD1A1",
    "paragraph_title": "#F368E0",
    "reference": "#EE5A24",
    "reference_content": "#FFC312",
    "seal": "#C44569",
    "table": "#3DC1D3",
    "text": "#E77F67",
    "vertical_text": "#786FA6",
    "vision_footnote": "#F8A5C2",
}


class RenderError(Exception):
    pass


def append_log(log_file: Optional[str], payload: Dict[str, object]) -> None:
    if not log_file:
        return
    path = Path(log_file).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer value: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def parse_page_image(value: str) -> Tuple[int, Path]:
    try:
        page_str, path_str = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected PAGE=PATH") from exc
    page = positive_int(page_str)
    path = Path(path_str).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"page image not found: {path}")
    return page, path


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replace document-parsing image placeholders with cropped image files."
    )
    parser.add_argument("markdown", help="Markdown file path, or - to read from stdin")
    parser.add_argument("--image", help="Single source page image for all placeholders")
    parser.add_argument(
        "--page-image",
        action="append",
        default=[],
        metavar="PAGE=PATH",
        help="Map a page marker like '--- Page 3 ---' to its source image",
    )
    parser.add_argument(
        "--source-path",
        help="Optional original image or PDF path used to derive default output locations",
    )
    parser.add_argument("--output-dir", help="Directory to write cropped images")
    parser.add_argument("--output-markdown", help="Optional output Markdown path")
    parser.add_argument(
        "--path-mode",
        choices=["relative", "absolute"],
        default="relative",
        help="How to write cropped image paths into Markdown",
    )
    parser.add_argument(
        "--prefix",
        default="doc-image",
        help="Filename prefix for cropped image assets",
    )
    parser.add_argument(
        "--default-page-number",
        type=positive_int,
        default=1,
        help="Page number to use for naming when the markdown has no explicit page markers",
    )
    parser.add_argument(
        "--render-overlay",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether to save a per-page overlay image with colored boxes",
    )
    parser.add_argument("--log-file", help="Optional JSONL log file for invocation records")
    args = parser.parse_args(argv)
    if not args.image and not args.page_image:
        parser.error("one of --image or --page-image is required")
    return args


def load_markdown(path_value: str) -> str:
    if path_value == "-":
        return sys.stdin.read()
    return Path(path_value).read_text(encoding="utf-8")


def parse_coords(raw: str) -> Tuple[int, int, int, int]:
    values = [int(a or b) for a, b in COORD_PATTERN.findall(raw)]
    if len(values) != 4:
        raise RenderError(f"expected 4 coordinates, got {len(values)} from: {raw}")
    return values[0], values[1], values[2], values[3]


def norm_to_pixels(coords: Tuple[int, int, int, int], width: int, height: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = coords
    left = int(x1 / 1000 * width)
    top = int(y1 / 1000 * height)
    right = int(x2 / 1000 * width)
    bottom = int(y2 / 1000 * height)
    if right <= left or bottom <= top:
        raise RenderError(f"invalid crop box after normalization: {coords}")
    return left, top, right, bottom


def page_spans(markdown: str, default_page_number: int = 1) -> Iterable[Tuple[int, int, int]]:
    markers = list(PAGE_MARKER_PATTERN.finditer(markdown))
    if not markers:
        yield default_page_number, 0, len(markdown)
        return
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(markdown)
        yield int(marker.group("page")), start, end


def build_page_lookup(args: argparse.Namespace) -> Dict[int, Path]:
    lookup: Dict[int, Path] = {}
    if args.image:
        image_path = Path(args.image).expanduser().resolve()
        if not image_path.is_file():
            raise RenderError(f"image file not found: {image_path}")
        lookup[args.default_page_number] = image_path
    for raw in args.page_image:
        page, path = parse_page_image(raw)
        lookup[page] = path
    return lookup


def resolve_source_path(args: argparse.Namespace, page_lookup: Dict[int, Path]) -> Path:
    if args.source_path:
        source_path = Path(args.source_path).expanduser().resolve()
        if not source_path.exists():
            raise RenderError(f"source path not found: {source_path}")
        return source_path
    page_numbers = sorted(page_lookup)
    if not page_numbers:
        raise RenderError("no source image available to derive output paths")
    return page_lookup[page_numbers[0]]


def resolve_output_paths(
    args: argparse.Namespace,
    source_path: Path,
) -> Tuple[Path, Optional[Path], Path]:
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        output_dir = source_path.parent / f"{source_path.stem}.assets"

    if args.output_markdown:
        output_markdown = Path(args.output_markdown).expanduser().resolve()
    elif args.markdown != "-":
        output_markdown = source_path.parent / f"{source_path.stem}.md"
    else:
        output_markdown = source_path.parent / f"{source_path.stem}.md"

    relative_base = output_markdown.parent if output_markdown is not None else output_dir.parent
    return output_dir, output_markdown, relative_base


def load_font(size: int = 16) -> ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        path = Path(candidate)
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except (OSError, IOError):
                continue
    return ImageFont.load_default()


def hex_to_rgb(color: str) -> Tuple[int, int, int]:
    value = color.lstrip("#")
    if len(value) != 6:
        return (255, 165, 0)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def save_overlay_image(
    image_path: Path,
    boxes: List[Tuple[str, Tuple[int, int, int, int]]],
    output_path: Path,
) -> None:
    image = Image.open(image_path).convert("RGBA")
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw = ImageDraw.Draw(image)
    font = load_font()

    for label, (left, top, right, bottom) in boxes:
        rgb = hex_to_rgb(DEFAULT_COLORS.get(label, "#CCCCCC"))
        draw_overlay.rectangle([left, top, right, bottom], fill=(*rgb, 40))
        draw.rectangle([left, top, right, bottom], outline=(*rgb, 255), width=3)

        text_bbox = font.getbbox(label)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        label_x = left
        label_y = max(0, top - text_height - 6)
        draw.rectangle(
            [label_x, label_y, label_x + text_width + 6, label_y + text_height + 4],
            fill=(*rgb, 255),
        )
        draw.text((label_x + 3, label_y + 2), label, fill=(255, 255, 255, 255), font=font)

    rendered = Image.alpha_composite(image, overlay).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered.save(output_path)


def render_markdown(
    markdown: str,
    page_lookup: Dict[int, Path],
    output_dir: Path,
    prefix: str,
    path_mode: str,
    relative_base: Optional[Path] = None,
    render_overlay: bool = True,
) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    image_cache: Dict[Path, Image.Image] = {}
    crop_index = 0
    overlay_boxes: Dict[int, List[Tuple[str, Tuple[int, int, int, int]]]] = {}

    result = []
    last = 0
    span_map = list(page_spans(markdown, default_page_number=min(page_lookup) if page_lookup else 1))
    for page_number, start, end in span_map:
        marker_match = None
        for candidate in PAGE_MARKER_PATTERN.finditer(markdown, last, start):
            marker_match = candidate
        if marker_match is not None:
            result.append(markdown[last:marker_match.end()])
            last = marker_match.end()
        segment = markdown[start:end]
        page_image_path = page_lookup.get(page_number) or page_lookup.get(1)
        if page_image_path is None:
            raise RenderError(f"no source image configured for page {page_number}")
        if page_image_path not in image_cache:
            image_cache[page_image_path] = Image.open(page_image_path).convert("RGB")
        page_image = image_cache[page_image_path]
        width, height = page_image.size

        def replace_again(match: Match[str]) -> str:
            nonlocal crop_index
            label = match.group("label") or match.group("label_box") or "image"
            raw_coords = match.group("coords") or match.group("box_coords") or ""
            crop_index += 1
            norm_box = parse_coords(raw_coords)
            pixel_box = norm_to_pixels(norm_box, width, height)
            overlay_boxes.setdefault(page_number, []).append((label, pixel_box))
            cropped = page_image.crop(pixel_box)
            filename = f"{prefix}-p{page_number:03d}-{crop_index:03d}.png"
            output_path = output_dir / filename
            cropped.save(output_path)
            base_dir = relative_base or output_dir.parent
            if path_mode == "absolute":
                rendered_path = output_path
            else:
                rendered_path = Path(os.path.relpath(output_path, start=base_dir))
            return f"![{label}]({rendered_path.as_posix()})"

        result.append(IMAGE_PATTERN.sub(replace_again, segment))
        last = end
    result.append(markdown[last:])

    if render_overlay:
        for page_number, boxes in overlay_boxes.items():
            page_image_path = page_lookup.get(page_number) or page_lookup.get(1)
            if page_image_path is None:
                raise RenderError(f"no source image configured for page {page_number}")
            overlay_path = output_dir / f"{prefix}-p{page_number:03d}-overlay.png"
            save_overlay_image(page_image_path, boxes, overlay_path)

    return "".join(result)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = None
    try:
        args = parse_args(argv)
        append_log(
            args.log_file,
            {
                "script": "render_doc_markdown",
                "status": "started",
                "markdown": args.markdown,
                "path_mode": args.path_mode,
                "prefix": args.prefix,
                "render_overlay": args.render_overlay,
            },
        )
        markdown = load_markdown(args.markdown)
        page_lookup = build_page_lookup(args)
        source_path = resolve_source_path(args, page_lookup)
        output_dir, output_markdown, relative_base = resolve_output_paths(args, source_path)
        rendered = render_markdown(
            markdown=markdown,
            page_lookup=page_lookup,
            output_dir=output_dir,
            prefix=args.prefix,
            path_mode=args.path_mode,
            relative_base=relative_base,
            render_overlay=args.render_overlay,
        )
        if output_markdown:
            output_markdown.parent.mkdir(parents=True, exist_ok=True)
            output_markdown.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
        append_log(
            args.log_file,
            {
                "script": "render_doc_markdown",
                "status": "succeeded",
                "page_image_count": len(page_lookup),
                "output_dir": str(output_dir),
                "output_markdown": str(output_markdown) if output_markdown else None,
                "render_overlay": args.render_overlay,
            },
        )
        return 0
    except RenderError as exc:
        append_log(
            getattr(args, "log_file", None),
            {
                "script": "render_doc_markdown",
                "status": "failed",
                "error": str(exc),
            },
        )
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
