# Mode: document parsing

## When to Use

- Need to convert one or more document page images into Markdown with high fidelity.
- Need structured output covering text, formulas, tables, and image placeholders.
- Need strict page order preservation for multi-page input.

## Standard Prompt

Use this prompt as the base prompt:

```text
You are an AI assistant specialized in converting document images (one or multiple pages extracted from a PDF) into Markdown with high fidelity.

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
- Do not include any explanations, metadata, or comments.
```

## Output Format

- Markdown only
- Multi-page output uses:

```text
--- Page N ---
```

- Inline formulas use `$...$`
- Block formulas use:

```text
$$
...
$$
```

- Tables must be HTML
- Images must use:

```text
![label](<box>[[x1, y1, x2, y2]]</box>)
```

## Coordinate Format

- `x1, y1, x2, y2` are normalized coordinates on a `0-1000` scale
- Use them exactly in the image placeholder format

## Default Parameters

- `TEMPERATURE = 0.3`

Complex-layout settings:

- `MIN_DYNAMIC_PATCH = 8`
- `MAX_DYNAMIC_PATCH = 24`

Use the complex settings for newspapers, magazines, and other dense multi-column layouts.

## Required CLI Mapping

When calling `scripts/qianfan_ocr_cli.py` for this mode:

- for complex layouts, also pass:
  - `--min-dynamic-patch 8`
  - `--max-dynamic-patch 24`

Example:

```bash
python3 "<skill-root>/scripts/qianfan_ocr_cli.py" "<document parsing prompt>" \
  --image <page_image>
```

Complex layout example:

```bash
python3 "<skill-root>/scripts/qianfan_ocr_cli.py" "<document parsing prompt>" \
  --image <page_image> \
  --min-dynamic-patch 8 \
  --max-dynamic-patch 24
```

For multiple independent page images that should be parsed concurrently instead of as one joint
multi-image request:

```bash
python3 "<skill-root>/scripts/qianfan_ocr_cli.py" "<document parsing prompt>" \
  --image <page1_image> \
  --image <page2_image> \
  --image <page3_image> \
  --batch \
  --concurrency 3
```

In this mode:

- each image is parsed independently
- results are returned as a JSON array
- `--concurrency` controls how many images run in parallel

Preferred one-step runner:

```bash
python3 "<skill-root>/scripts/run_document_parsing.py" <image_or_pdf>
```

Preferred PDF runner:

```bash
python3 "<skill-root>/scripts/run_pdf_document_parsing.py" <pdf> --pages all
python3 "<skill-root>/scripts/run_pdf_document_parsing.py" <pdf> --pages 3
python3 "<skill-root>/scripts/run_pdf_document_parsing.py" <pdf> --pages 3-5 --request-mode joint
python3 "<skill-root>/scripts/run_pdf_document_parsing.py" <pdf> --pages 3-5 --request-mode batch --concurrency 3
```

This runner:

- calls `qianfan_ocr_cli.py` with the document parsing prompt
- saves the raw markdown to `<source_stem>.raw.md`
- renders image placeholders into `<source_stem>.assets/`
- writes the final markdown to `<source_stem>.md`

For PDF input, `scripts/run_pdf_document_parsing.py` additionally writes:

- combined markdown: `<source_stem>.md`
- shared assets: `<source_stem>.assets/`
- per-page markdown files: `<source_stem>.pages/pNNN.md`

It also supports:

- `--request-mode joint`: send the selected pages as one multi-image request
- `--request-mode batch`: send one request per page
- `--concurrency <N>`: used with `--request-mode batch` to parse multiple selected pages concurrently

Use `--request-mode joint` when the selected pages have cross-page semantic dependency and should be
understood together in one request.

Use `--request-mode batch` when each page can be parsed independently and throughput matters more.

## Rendering Note

Raw model Markdown may contain image placeholders such as:

```text
![image](<box>[[<COORD_078>, <COORD_126>, <COORD_443>, <COORD_228>]]</box>)
```

These are not directly renderable by normal Markdown viewers. Post-process them with:

```bash
python3 "<skill-root>/scripts/render_doc_markdown.py" parsed.md --image page.png --output-dir rendered-assets --output-markdown rendered.md
```

This script crops the referenced box from the original page image and rewrites the placeholder to a
real image path.

If `--output-dir` and `--output-markdown` are omitted, the script writes:

- Markdown: next to the original image / PDF source, using `<source_stem>.md`
- Assets: next to the original image / PDF source, using `<source_stem>.assets/`
