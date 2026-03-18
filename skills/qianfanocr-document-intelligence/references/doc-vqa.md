# Mode: doc vqa

## When to Use

- Need to answer a specific question grounded in a document image or PDF page.

## Prompt Rule

- Simple question: ask the question directly.
- Complex question: ask the question directly and append `<think>` through thinking mode.

## Thinking vs Non-Thinking

- non-thinking output: direct answer
- thinking output: `<think>...</think>` + direct answer

Thinking content may contain:

```text
<box>[[x1, y1, x2, y2]]</box><label>category</label><brief>description</brief>
```

Coordinate tokens may appear as `<COORD_N>`.

## Default Parameters

- `temperature = 0.0`
- `max_patch_num = 12`

## Required CLI Mapping

When calling `scripts/qianfan_ocr_cli.py` for this mode:

- for simple questions:
  - ask the question directly
- for complex questions:
  - ask the question directly
  - always pass `--thinking`
