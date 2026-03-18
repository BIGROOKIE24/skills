# Mode: layout analysis

## When to Use

- Need all layout elements on a document page.
- Need `bbox` plus `category`.
- Need no OCR text in the output.

## Standard Prompt

Use this prompt directly:

```text
Extract all layout elements from this image.
Output in JSON format. Each element must include:
1.  `bbox`: `[x1, y1, x2, y2]`
2.  `category`: One of ['abstract', 'algorithm', 'aside_text', 'chart', 'content', 'display_formula', 'inline_formula', 'doc_title', 'figure_title', 'footer', 'footer_image', 'footnote', 'formula_number', 'header', 'header_image', 'image', 'number', 'paragraph_title', 'reference', 'reference_content', 'seal', 'table', 'text', 'vertical_text', 'vision_footnote']

**Important**: Do not include any extracted text in the output.
```

## Output Format

Return JSON only.

Each item must look like:

```json
{
  "bbox": [x1, y1, x2, y2],
  "category": "text"
}
```

## Coordinates

This format supports two coordinate encodings:

- token format: `<COORD_159>`
- plain numeric format: `159`

Normalize `<COORD_N>` to `N` before parsing.

Coordinate range:

- normalized to `[0, 1000)`

Pixel recovery formula:

```text
x_pixel = COORD / 1000 * W
y_pixel = COORD / 1000 * H
```

## Categories

- `abstract`
- `algorithm`
- `aside_text`
- `chart`
- `content`
- `display_formula`
- `inline_formula`
- `doc_title`
- `figure_title`
- `footer`
- `footer_image`
- `footnote`
- `formula_number`
- `header`
- `header_image`
- `image`
- `number`
- `paragraph_title`
- `reference`
- `reference_content`
- `seal`
- `table`
- `text`
- `vertical_text`
- `vision_footnote`

Preferred one-step runner:

```bash
python3 "<skill-root>/scripts/run_layout_analysis.py" <image_or_pdf>
```

When calling `scripts/qianfan_ocr_cli.py` for this mode:

This runner writes results next to the source file:

- layout json: `<source_stem>_layout.json`
- layout overlay image: `<source_stem>_layout_overlay.png`
