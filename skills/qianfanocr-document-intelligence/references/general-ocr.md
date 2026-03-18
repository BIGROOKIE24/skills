# Mode: general ocr

## When to Read

- Need all visible text from an image or PDF page.
- Document structure is not important.
- Task is plain OCR rather than parsing or field extraction.

## Fixed Prompt

Use this prompt as-is:

```text
请识别图片中的所有文字内容。

输出格式要求：
1. 按原文分行，用换行符分隔
2. 按照图片中语言的自然阅读顺序输出
3. 仅返回识别的文字内容，不要添加其他说明
```

## CLI Guidance

- Do not use `--thinking`.
- Run one image or one PDF page per call unless joint context is necessary.

## Output Emphasis

- `extracted_text`: primary output
- `evidence`: major text regions or lines when useful
- `warnings`: blur, occlusion, rotation, truncation

## When Not to Use

- Need document structure: use `document parsing`.
- Need only key fields: use `key information extraction`.
- Need answers to a specific question: use `doc vqa`.
