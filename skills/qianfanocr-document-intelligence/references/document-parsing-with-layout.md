# Mode: document parsing with layout

## When to Use

- Need final Markdown output.
- Need the model to reason over layout first.
- Page contains formulas, charts, tables, images, side notes, or complex multi-column structure.

## Thinking vs Non-Thinking

Mode comparison:

- non-thinking: prompt without `<think>`, output is Markdown directly
- thinking: prompt ends with `<think>`, output is `<think>...</think>` plus final Markdown

## Standard Prompt

Use this prompt body:

```text
你是一个专门将 PDF 中提取的文档页面图像（单页或多页）转换为 Markdown 的 AI 助手。

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
- 不得包含任何解释性文字、元信息或注释。
```

## Thinking Output Format

Thinking output may include layout snippets in this form:

```text
<box>[[x1, y1, x2, y2]]</box><label>category</label><brief>description</brief>
```

Coordinate tokens may also appear as `<COORD_N>`.

## Thinking Labels

- `text`
- `vertical_text`
- `paragraph_title`
- `doc_title`
- `abstract`
- `content`
- `reference`
- `reference_content`
- `header_image`
- `header`
- `footer`
- `footer_image`
- `footnote`
- `number`
- `image`
- `seal`
- `chart`
- `table`
- `figure_title`
- `vision_footnote`
- `display_formula`
- `formula_number`
- `algorithm`
- `aside_text`
- `inline_formula`

## Default Parameters

- `temperature = 0.0`
- `top_p = 0.9`
- `max_patch_num = 24`

## Required CLI Mapping

When calling `scripts/qianfan_ocr_cli.py` for this mode:

- always pass `--thinking`

If the page is visually dense, also pass:

- `--min-dynamic-patch 8`
- `--max-dynamic-patch 24`

Preferred one-step runner:

```bash
python3 "<skill-root>/scripts/run_document_parsing_with_layout.py" <image_or_pdf>
```

This runner writes results next to the source file:

- rendered markdown: `<source_stem>_layout.md`
- markdown before image replacement: `<source_stem>_layout.raw.md`
- rendered assets: `<source_stem>_layout.assets/`
- parsed think/layout result: `<source_stem>_layout.json`
- page overlay from think/layout result: `<source_stem>_layout_overlay.png`

## Rendering Note

If the final Markdown still contains image placeholders in `<box>[[...]]</box>` form, run:

```bash
python3 "<skill-root>/scripts/render_doc_markdown.py" parsed.md --image page.png --output-dir rendered-assets --output-markdown rendered.md
```

to crop the corresponding regions from the source page image and replace the placeholders with
renderable image paths.

If `--output-dir` and `--output-markdown` are omitted, the script writes the Markdown file and the
`.assets/` directory next to the original image / PDF source.
