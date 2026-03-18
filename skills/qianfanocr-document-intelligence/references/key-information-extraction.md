# Mode: key information extraction

## When to Read

- Need key fields from cards, invoices, receipts, forms, contracts, certificates, or similar documents.
- Need JSON output rather than plain text or Markdown.
- Need either schema-constrained extraction or schema-free key information extraction.

## Goal

Extract clear, reliable key information only. Do not guess missing or blurry values.

## Schema Selection Rule

Choose the prompt branch based on user intent:

- Use `Without explicit schema` when the user asks for all key-value information, all key fields,
  all structured information, all important fields, or does not specify an exact field list.
- Use `With explicit schema` only when the user explicitly provides a concrete field list, schema,
  JSON keys, or a fixed set of target fields to extract.

Examples that should use `Without explicit schema`:

- `我想知道这里面所有的key value信息`
- `提取图片中的所有关键信息`
- `把表单里的字段和值都整理成json`

Examples that should use `With explicit schema`:

- `提取姓名、证件号、有效期`
- `按这个schema抽取：{"name":"","id_number":"","expiry_date":""}`
- `只提取合同编号、签署日期、甲乙双方`

## Prompt Templates

### With explicit schema

```text
请从图片中提取以下信息："{{Key 列表}}"
注意：
1. 字段名与图像中的原始文字含义一致，但不一定完全一样。
2. 仅提取清晰可见且可确定的文字内容；模糊、缺失或无法确认的部分请忽略，不要猜测或补全。
3. 值完整提取及格式保持：提取完整的字段值，包括数字、符号、单位等，保持原始格式，包括空格、标点符号等。

输出格式要求：
- 使用标准JSON格式
- 字段名使用双引号包围
- 字段值保持原始格式
- 确保JSON格式正确可解析
```

### Without explicit schema

```text
请以json格式输出图像中的关键信息。
```

Recommended stronger version for open-ended key-value extraction:

```text
请以json格式输出图像中的所有关键信息（key-value信息）。
注意：
1. 尽量覆盖图片中清晰可见且有明确语义的字段及其对应值。
2. 字段名应尽量贴近图像中的原始表达；如果原图没有明确字段名，可使用语义准确、简洁的归纳字段名。
3. 仅提取清晰可见且可确定的内容；模糊、缺失或无法确认的部分请忽略，不要猜测或补全。
4. 值完整提取并保持原始格式，包括数字、符号、单位、空格和标点。

输出格式要求：
- 使用标准JSON格式
- 字段名使用双引号包围
- 字段值保持原始格式
- 确保JSON格式正确可解析
```

## CLI Guidance

- Default to no `--thinking`.
- Use `--thinking` only when the fields are spread across a complex layout and reading order matters.

## Decision Rule

If the user asks for all fields rather than a specified field list, do not synthesize a schema on
the agent side. Use the `Without explicit schema` prompt branch directly.

## Output Emphasis

- `structured_data`: primary JSON-like result
- `answer`: concise summary of what was extracted
- `warnings`: missing fields, low-confidence regions, truncated pages

## When Not to Use

- Need complete page text: use `general ocr`.
- Need full Markdown reconstruction: use `document parsing`.
- Need question answering over the document: use `doc vqa`.
