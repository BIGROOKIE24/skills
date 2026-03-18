# Mode: element recognition

## When to Use

- Input is already cropped to a single text block, formula block, or table block.
- Need exact recognition on the cropped element.

## Standard Prompts

### Text recognition

```text
Please extract the text from the image.
```

Output:

- text only

### Formula recognition

```text
Please convert the formula in the image to LaTeX.
```

Output:

- LaTeX only

### Table recognition

```text
Please convert the table in the image to HTML.
```

Output:

- HTML only

## Preferred Runner

Use the one-step runner for this mode:

```bash
python3 "<skill-root>/scripts/run_element_recognition.py" <cropped_image_or_pdf> --element-type <text|formula|table>
```

Default outputs:

- image input: `<source_stem>.md`
- PDF input: `<source_stem>_pNNN.md`

This mode does not generate any `assets` directory.
