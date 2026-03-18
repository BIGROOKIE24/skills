#!/usr/bin/env python3

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import List, Optional, Sequence, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent

DOCUMENT_PARSING_WITH_LAYOUT_PROMPT = """你是一个专门将 PDF 中提取的文档页面图像（单页或多页）转换为 Markdown 的 AI 助手。

你的任务是严格按照以下规则，将图像中所有可见内容准确转换为 Markdown。不得添加任何解释、评论或推断内容。

1. 页面：
- 输入可能包含一页或多页文档图像。
- 必须严格保持输入提供的页面顺序。
- 如果包含多页，请使用以下标记分隔页面：
  --- Page N ---
  （N 从 1 开始）
- 如果只有一页，请不要输出任何页面分隔符。

2. 文本识别：
- 准确转换所有可见文本内容。
- 不得猜测、推断、改写或纠正文本。
- 保留原始文档结构，包括但不限于：标题、段落、列表、图注、脚注等。
- 必须完整保留每一页中的页眉和页脚文本。

3. 阅读顺序：
- 按照自上而下、从左到右的顺序进行内容读取。
- 对于多栏排版，必须先完整读取左栏，再读取右栏。
- 不得为了语义或逻辑清晰度而调整内容顺序。

4. 数学公式：
- 将所有数学表达式转换为 LaTeX 格式。
- 行内公式必须使用 $...$。
- 行间（块级）公式必须使用：
  $$
  ...
  $$
- 必须严格保留原有符号、结构和排版。
- 不得编造、简化、规范化或纠正公式内容。

5. 表格：
- 所有表格必须转换为 HTML 格式。
- 使用 <table> 和 </table> 包裹整个表格。
- 保留原有的行列结构，包括合并单元格（rowspan、colspan）和空单元格。
- 不得重新组织或重新解释表格内容。

6. 图片：
- 不得描述图片内容。
- 必须使用以下格式保留所有图片元素：
  ![label](<box>[[x1, y1, x2, y2]]</box>)
- 允许的 label 仅包括：
  image, chart, header_image, footer_image, seal
- 不得引入新的 label。
- 不得删除、合并或重排图片元素。

7. 无法识别或缺失内容：
- 如果文本、符号或表格单元格无法识别，应保留其位置并将内容置空。
- 不得猜测或补全缺失内容。

8. 输出要求：
- 仅输出 Markdown 内容。
- 尽可能保留原始布局、间距和结构。
- 使用适当的换行清晰分隔不同元素。
- 不得包含任何解释性文字、元信息或注释。"""

THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL)
LAYOUT_ENTRY_PATTERN = re.compile(
    r"<box>(?P<box>.*?)</box>\s*<label>(?P<label>.*?)</label>\s*<brief>(?P<brief>.*?)</brief>",
    re.DOTALL,
)


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
        description="Run document parsing with layout end-to-end and export markdown + layout JSON."
    )
    parser.add_argument("source", help="Source image path or PDF path")
    parser.add_argument("--page", type=int, default=1, help="1-based PDF page number to parse")
    parser.add_argument("--max-tokens", type=int, help="Optional max_tokens override")
    parser.add_argument("--output-markdown", help="Optional final rendered markdown path")
    parser.add_argument("--output-dir", help="Optional rendered assets directory")
    parser.add_argument("--raw-markdown", help="Optional markdown-before-render path")
    parser.add_argument("--layout-json", help="Optional layout json output path")
    parser.add_argument("--layout-overlay", help="Optional layout overlay image path")
    parser.add_argument("--log-file", help="Optional shared JSONL log file")
    parser.add_argument(
        "--no-render-overlay",
        action="store_true",
        help="Disable markdown placeholder overlay generation",
    )
    return parser.parse_args(argv)


def extract_thinking_and_markdown(text: str) -> Tuple[str, str]:
    match = THINK_PATTERN.search(text)
    if not match:
        return "", text.strip()
    thinking = match.group(1).strip()
    markdown = text[match.end():].strip()
    return thinking, markdown


def parse_layout_entries(thinking_text: str):
    render_doc_markdown = load_script_module("render_doc_markdown")
    entries = []
    for match in LAYOUT_ENTRY_PATTERN.finditer(thinking_text):
        bbox = render_doc_markdown.parse_coords(match.group("box"))
        entries.append(
            {
                "bbox": list(bbox),
                "label": match.group("label").strip(),
                "brief": match.group("brief").strip(),
            }
        )
    return entries


def derive_output_paths(source: Path, page: int, args: argparse.Namespace):
    page_suffix = f"_p{page:03d}" if source.suffix.lower() == ".pdf" else ""
    stem = f"{source.stem}{page_suffix}_layout"
    final_markdown = (
        Path(args.output_markdown).expanduser().resolve()
        if args.output_markdown
        else source.parent / f"{stem}.md"
    )
    raw_markdown = (
        Path(args.raw_markdown).expanduser().resolve()
        if args.raw_markdown
        else source.parent / f"{stem}.raw.md"
    )
    assets_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else source.parent / f"{stem}.assets"
    )
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
    return final_markdown, raw_markdown, assets_dir, layout_json, layout_overlay


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
        run_document_parsing = load_script_module("run_document_parsing")
        qianfan_cli = load_script_module("qianfan_ocr_cli")
        render_doc_markdown = load_script_module("render_doc_markdown")

        source = run_document_parsing.resolve_source(args.source)
        page_image = run_document_parsing.resolve_page_image(source, args.page, args.log_file)
        final_markdown, raw_markdown, assets_dir, layout_json, layout_overlay = derive_output_paths(
            source, args.page, args
        )

        qianfan_cli.append_log(
            args.log_file,
            {
                "script": "run_document_parsing_with_layout",
                "status": "started",
                "source": str(source),
                "page_image": str(page_image),
            },
        )

        cli_args = qianfan_cli.parse_args(
            [
                DOCUMENT_PARSING_WITH_LAYOUT_PROMPT,
                "--image",
                str(page_image),
                "--thinking",
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
        thinking_text, markdown_text = extract_thinking_and_markdown(raw_content)
        layout_entries = parse_layout_entries(thinking_text)

        raw_markdown.parent.mkdir(parents=True, exist_ok=True)
        raw_markdown.write_text(markdown_text, encoding="utf-8")

        layout_json.parent.mkdir(parents=True, exist_ok=True)
        layout_json.write_text(json.dumps(layout_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        page_lookup = {1: page_image}
        render_args = render_doc_markdown.parse_args(
            [
                str(raw_markdown),
                "--image",
                str(page_image),
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
        source_path = render_doc_markdown.resolve_source_path(render_args, page_lookup)
        output_dir, output_markdown, relative_base = render_doc_markdown.resolve_output_paths(
            render_args, source_path
        )
        rendered_markdown = render_doc_markdown.render_markdown(
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
        output_markdown.write_text(rendered_markdown, encoding="utf-8")

        if layout_entries:
            boxes = []
            with ImageProxy(page_image) as image_proxy:
                width, height = image_proxy.size
                for item in layout_entries:
                    pixel_box = render_doc_markdown.norm_to_pixels(tuple(item["bbox"]), width, height)
                    boxes.append((item["label"], pixel_box))
            render_doc_markdown.save_overlay_image(page_image, boxes, layout_overlay)

        qianfan_cli.append_log(
            args.log_file,
            {
                "script": "run_document_parsing_with_layout",
                "status": "succeeded",
                "final_markdown": str(output_markdown),
                "raw_markdown": str(raw_markdown),
                "assets_dir": str(output_dir),
                "layout_json": str(layout_json),
                "layout_overlay": str(layout_overlay),
                "layout_count": len(layout_entries),
            },
        )

        json.dump(
            {
                "source": str(source),
                "final_markdown": str(output_markdown),
                "raw_markdown": str(raw_markdown),
                "assets_dir": str(output_dir),
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
