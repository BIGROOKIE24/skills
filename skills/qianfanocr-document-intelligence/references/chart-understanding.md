# Mode: chart understanding

## Standard Prompt Patterns

### Description

```text
介绍一下以下这张图表
```

### Structured JSON extraction

```text
任务目标：请将图片中的统计图表解析成字典形式，输出为json格式。
输出要求：
    1. 提取图表中的信息组织为字典格式。
    2. 严格按照输出格式输出，不要输出额外其他内容。
输出格式
```json
xxx
```
```

### Chart QA / trend analysis

```text
下面的这张图表里能得出什么结论？怎么看待2025-2030的走势
```

## Output Format

- Description task: direct answer
- Structured extraction task: JSON only
- QA task: direct answer, optionally followed by concise support
