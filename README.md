# md2tex

A Markdown to LaTeX converter written in Python.

## Features

`md2tex` converts Markdown files (e.g. `Ch01.md`) to well-formed LaTeX
(`Ch01.tex`), handling:

| Markdown feature | LaTeX output |
|---|---|
| Block quotes — tab-indented **or** `>` prefix | `\begin{quote}...\end{quote}` |
| HTML tables (`<table>…</table>`) | `\begin{tabular}` with `\hline` separators |
| Inline math (`$…$`) and display math (`$$…$$`, `\[…\]`) | preserved verbatim |
| Figures `![alt](subdir/img.png "Caption")` | `\begin{figure}` with `\includegraphics`, `\caption`, `\label` |
| Headings `#`–`######` | `\section` → `\subparagraph` |
| Bold, italic, inline code, hyperlinks | `\textbf`, `\textit`, `\texttt`, `\href` |
| Fenced code blocks | `\begin{verbatim}...\end{verbatim}` |
| Unordered / ordered lists | `itemize` / `enumerate` |
| Horizontal rules (`---`) | `\hrule` |

The generated document includes the standard packages: `amsmath`, `graphicx`,
`hyperref`, and `booktabs`.

## Requirements

* Python 3.10+
* No third-party libraries — uses only the Python standard library

## Usage

```bash
# Convert Ch01.md → Ch01.tex
python md2tex.py Ch01.md

# Specify a custom output path
python md2tex.py Ch01.md output/Ch01.tex
```

### Programmatic API

```python
import md2tex

# Convert a string
latex = md2tex.convert(markdown_text, standalone=True)

# Convert body only (no \documentclass wrapper)
body = md2tex.convert(markdown_text, standalone=False)

# Convert a file
out_path = md2tex.convert_file("Ch01.md")          # → Ch01.tex
out_path = md2tex.convert_file("Ch01.md", "out.tex")
```

## Example

See [`examples/Ch01.md`](examples/Ch01.md) for a sample input that exercises
every supported feature.

## Tests

```bash
pip install pytest
python -m pytest tests/
```
