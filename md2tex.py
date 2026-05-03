#!/usr/bin/env python3
"""md2tex: Convert Markdown files to well-formed LaTeX.

Supported input features:
- Block quotes (tab-indented lines or standard ``>`` prefix)
- Tables in HTML (``<table>``...``</table>``)
- Equations in Math TeX / LaTeX (``$...$``, ``$$...$$``, ``\\(...\\)``, ``\\[...\\]``)
- Figures in Markdown reference format pointing to a subdirectory
  (``![alt](subdir/image.ext "Caption")``)
- Headings (``#`` … ``######``)
- Bold, italic, inline code, hyperlinks
- Fenced code blocks
- Unordered and ordered lists
- Horizontal rules
"""

import os
import re
import sys
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# HTML table parser
# ---------------------------------------------------------------------------

class _TableParser(HTMLParser):
    """Collect rows/cells from a single HTML ``<table>`` block."""

    def __init__(self):
        super().__init__()
        self.rows = []           # list of (cells, is_header_flags)
        self._row = []
        self._row_flags = []
        self._cell_buf = []
        self._is_header = False
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row = []
            self._row_flags = []
        elif tag in ("td", "th"):
            self._is_header = tag == "th"
            self._cell_buf = []
            self._in_cell = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "tr":
            if self._row:
                self.rows.append((list(self._row), list(self._row_flags)))
        elif tag in ("td", "th"):
            self._row.append("".join(self._cell_buf).strip())
            self._row_flags.append(self._is_header)
            self._in_cell = False

    def handle_data(self, data):
        if self._in_cell:
            self._cell_buf.append(data)


def _html_table_to_latex(html: str) -> str:
    """Return a LaTeX ``tabular`` representation of *html*."""
    parser = _TableParser()
    parser.feed(html)
    if not parser.rows:
        return ""

    num_cols = max(len(r[0]) for r in parser.rows)
    col_spec = "|" + "l|" * num_cols

    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\begin{tabular}{" + col_spec + "}",
        r"\hline",
    ]

    for cells, flags in parser.rows:
        # Pad short rows.
        while len(cells) < num_cols:
            cells.append("")
            flags.append(False)

        formatted = []
        for cell, is_hdr in zip(cells, flags):
            cell = _escape_ampersands(cell)
            formatted.append(r"\textbf{" + cell + "}" if is_hdr else cell)
        lines.append(" & ".join(formatted) + r" \\")
        lines.append(r"\hline")

    lines += [r"\end{tabular}", r"\end{table}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LaTeX escaping helpers
# ---------------------------------------------------------------------------

# Math delimiters that must be left untouched (an unescaped & inside, e.g.,
# an align/matrix environment, is meaningful to LaTeX).  Ordered longest-first
# so $$...$$ is matched before $...$.
_MATH_PATTERNS = [
    (re.compile(r"\$\$.*?\$\$", re.DOTALL)),
    (re.compile(r"\\\[.*?\\\]", re.DOTALL)),
    (re.compile(r"\\\(.*?\\\)", re.DOTALL)),
    (re.compile(r"\$[^$\n]+?\$")),
]


def _with_math_protected(text: str, transform) -> str:
    """Apply *transform* to *text* with math regions stashed out of the way."""
    stash: list[str] = []

    def _stash(m: re.Match) -> str:
        stash.append(m.group(0))
        return f"\x00MATH{len(stash) - 1}\x00"

    for pattern in _MATH_PATTERNS:
        text = pattern.sub(_stash, text)

    text = transform(text)

    for idx, math in enumerate(stash):
        text = text.replace(f"\x00MATH{idx}\x00", math)
    return text


def _escape_ampersands(text: str) -> str:
    """Escape ``&`` as ``\\&`` outside math regions; leave ``\\&`` alone."""
    return _with_math_protected(text, lambda t: re.sub(r"(?<!\\)&", r"\\&", t))


# Unicode characters that the standard `verbatim` environment can't render
# reliably (the typewriter font lacks glyphs for them under several common
# LaTeX setups).  Mapped to ASCII equivalents that read sensibly in monospace.
_VERBATIM_UNICODE_MAP = {
    "–": "-",     # – en-dash
    "—": "--",    # — em-dash
    "‐": "-",     # ‐ hyphen
    "‑": "-",     # ‑ non-breaking hyphen
    "‘": "'",     # ‘ left single quote
    "’": "'",     # ’ right single quote
    "“": '"',     # “ left double quote
    "”": '"',     # ” right double quote
    "•": "*",     # • bullet
    "…": "...",   # … horizontal ellipsis
    " ": " ",     # NBSP
}


def _sanitize_verbatim(line: str) -> str:
    """Replace Unicode characters that misrender inside ``verbatim``."""
    for src, dst in _VERBATIM_UNICODE_MAP.items():
        if src in line:
            line = line.replace(src, dst)
    return line


def _normalize_quotes(text: str) -> str:
    """Convert ASCII/Unicode quotes to LaTeX-style ``\\`\\``...''`` and `` ` ``/``'``.

    ASCII ``"`` opens when not preceded by a non-space char, otherwise closes.
    Unicode smart quotes map directly to their LaTeX equivalents.  ASCII ``'``
    is left untouched (it doubles as an apostrophe and renders correctly).
    """
    def _do(t: str) -> str:
        # Unicode smart quotes — direct mapping.
        t = t.replace("“", "``").replace("”", "''")
        t = t.replace("‘", "`").replace("’", "'")
        # ASCII double quotes — open if not preceded by a non-space char.
        t = re.sub(r'(?<!\S)"', "``", t)
        t = t.replace('"', "''")
        return t

    return _with_math_protected(text, _do)


# ---------------------------------------------------------------------------
# Inline Markdown → LaTeX conversion
# ---------------------------------------------------------------------------

def _figure_repl(m: re.Match) -> str:
    alt = m.group(1)
    path = m.group(2).strip()
    caption = m.group(3).strip() if m.group(3) else alt
    # Build a safe label from the file's base name.
    basename = os.path.splitext(os.path.basename(path))[0]
    label = re.sub(r"[^a-zA-Z0-9]+", "", basename).lower()
    return (
        "\n"
        r"\begin{figure}[htbp]" + "\n"
        r"\centering" + "\n"
        r"\includegraphics[width=\columnwidth]{" + path + "}\n"
        r"\caption{" + caption + "}\n"
        r"\label{fig:" + label + "}\n"
        r"\end{figure}" + "\n"
    )


def _convert_inline(text: str) -> str:
    """Apply inline Markdown → LaTeX substitutions to *text*."""
    # Figures: ![alt](path "caption") or ![alt](path)
    text = re.sub(
        r'!\[([^\]]*)\]\(([^)"]+?)(?:\s+"([^"]*)")?\)',
        _figure_repl,
        text,
    )
    # Hyperlinks: [text](url)  — must come after figures
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\\href{\2}{\1}", text)
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"__(.+?)__", r"\\textbf{\1}", text)
    # Italic: *text* or _text_
    text = re.sub(r"\*(.+?)\*", r"\\textit{\1}", text)
    text = re.sub(r"(?<![a-zA-Z0-9])_(.+?)_(?![a-zA-Z0-9])", r"\\textit{\1}", text)
    # Inline code: `code`
    text = re.sub(r"`([^`]+)`", r"\\texttt{\1}", text)
    # Normalize ASCII/Unicode quote characters to LaTeX form.
    text = _normalize_quotes(text)
    # Escape stray ampersands (preserves math regions and existing \&)
    text = _escape_ampersands(text)
    return text


# ---------------------------------------------------------------------------
# Block-level conversion state machine
# ---------------------------------------------------------------------------

def _close_list(result: list, state: dict) -> None:
    if state["in_itemize"]:
        result.append(r"\end{itemize}")
        state["in_itemize"] = False
    if state["in_enumerate"]:
        result.append(r"\end{enumerate}")
        state["in_enumerate"] = False


def _close_quote(result: list, state: dict) -> None:
    if state["in_quote"]:
        result.append(r"\end{verbatim}")
        state["in_quote"] = False


def convert_body(content: str) -> str:
    """Convert Markdown *content* to a LaTeX body (no document wrapper)."""
    lines = content.splitlines()
    result: list[str] = []
    state = {
        "in_code_block": False,
        "in_html_table": False,
        "in_itemize": False,
        "in_enumerate": False,
        "in_quote": False,
        "in_display_math": None,   # None or the closing delimiter ('$$' / '\\]')
    }
    html_buf: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # ------------------------------------------------------------------ #
        # Fenced code block                                                    #
        # ------------------------------------------------------------------ #
        if re.match(r"^```", line):
            if not state["in_code_block"]:
                _close_list(result, state)
                _close_quote(result, state)
                state["in_code_block"] = True
                result.append(r"\begin{verbatim}")
            else:
                state["in_code_block"] = False
                result.append(r"\end{verbatim}")
            i += 1
            continue

        if state["in_code_block"]:
            result.append(_sanitize_verbatim(line))
            i += 1
            continue

        # ------------------------------------------------------------------ #
        # Display math block — pass through verbatim                           #
        # Opens on a line whose stripped form starts with $$ or \[, closes on  #
        # the matching delimiter.  Single-line $$...$$ on one line is handled  #
        # by the inline math regex in _convert_inline.                         #
        # ------------------------------------------------------------------ #
        if state["in_display_math"] is not None:
            result.append(line)
            if state["in_display_math"] in line.strip():
                state["in_display_math"] = None
            i += 1
            continue

        stripped = line.strip()
        if stripped.startswith("$$") and stripped.count("$$") == 1:
            _close_list(result, state)
            _close_quote(result, state)
            state["in_display_math"] = "$$"
            result.append(line)
            i += 1
            continue
        if stripped.startswith(r"\[") and r"\]" not in stripped:
            _close_list(result, state)
            _close_quote(result, state)
            state["in_display_math"] = r"\]"
            result.append(line)
            i += 1
            continue

        # ------------------------------------------------------------------ #
        # HTML table accumulation                                              #
        # ------------------------------------------------------------------ #
        if re.match(r"\s*<table", line, re.IGNORECASE):
            _close_list(result, state)
            _close_quote(result, state)
            state["in_html_table"] = True
            html_buf = [line]
            i += 1
            continue

        if state["in_html_table"]:
            html_buf.append(line)
            if re.search(r"</table>", line, re.IGNORECASE):
                state["in_html_table"] = False
                result.append(_html_table_to_latex("\n".join(html_buf)))
                html_buf = []
            i += 1
            continue

        # ------------------------------------------------------------------ #
        # Block quotes — tab-indented  (one tab or four spaces)               #
        # ------------------------------------------------------------------ #
        tab_quote = re.match(r"^(\t|    )(.*)$", line)
        if tab_quote:
            _close_list(result, state)
            if not state["in_quote"]:
                result.append(r"\begin{verbatim}")
                state["in_quote"] = True
            result.append(_sanitize_verbatim(tab_quote.group(2)))
            i += 1
            continue

        # Block quotes — standard ``>`` prefix
        std_quote = re.match(r"^>\s?(.*)", line)
        if std_quote:
            _close_list(result, state)
            if not state["in_quote"]:
                result.append(r"\begin{verbatim}")
                state["in_quote"] = True
            result.append(_sanitize_verbatim(std_quote.group(1)))
            i += 1
            continue

        # Close quote on non-quote line
        _close_quote(result, state)

        # ------------------------------------------------------------------ #
        # Headings                                                             #
        # ------------------------------------------------------------------ #
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            _close_list(result, state)
            level = len(heading.group(1))
            title = heading.group(2).strip()
            cmds = [
                "section",
                "subsection",
                "subsubsection",
                "paragraph",
                "subparagraph",
            ]
            cmd = cmds[min(level - 1, len(cmds) - 1)]
            result.append(f"\\{cmd}{{{_convert_inline(title)}}}")
            i += 1
            continue

        # ------------------------------------------------------------------ #
        # Unordered list                                                       #
        # ------------------------------------------------------------------ #
        ul = re.match(r"^(\s*)[*\-+]\s+(.+)$", line)
        if ul:
            if state["in_enumerate"]:
                result.append(r"\end{enumerate}")
                state["in_enumerate"] = False
            if not state["in_itemize"]:
                result.append(r"\begin{itemize}")
                state["in_itemize"] = True
            result.append(r"  \item " + _convert_inline(ul.group(2)))
            i += 1
            continue

        # ------------------------------------------------------------------ #
        # Ordered list                                                         #
        # ------------------------------------------------------------------ #
        ol = re.match(r"^(\s*)\d+\.\s+(.+)$", line)
        if ol:
            if state["in_itemize"]:
                result.append(r"\end{itemize}")
                state["in_itemize"] = False
            if not state["in_enumerate"]:
                result.append(r"\begin{enumerate}")
                state["in_enumerate"] = True
            result.append(r"  \item " + _convert_inline(ol.group(2)))
            i += 1
            continue

        # Close any open list on non-list content
        _close_list(result, state)

        # ------------------------------------------------------------------ #
        # Horizontal rule                                                      #
        # ------------------------------------------------------------------ #
        if re.match(r"^[-*_]{3,}\s*$", line):
            result.append(r"\hrule")
            i += 1
            continue

        # ------------------------------------------------------------------ #
        # Blank line                                                           #
        # ------------------------------------------------------------------ #
        if line.strip() == "":
            result.append("")
            i += 1
            continue

        # ------------------------------------------------------------------ #
        # Regular paragraph line                                               #
        # ------------------------------------------------------------------ #
        result.append(_convert_inline(line))
        i += 1

    # Close any environments still open at end of file.
    _close_list(result, state)
    _close_quote(result, state)
    if state["in_code_block"]:
        result.append(r"\end{verbatim}")

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Document wrapper
# ---------------------------------------------------------------------------

_PREAMBLE = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{hyperref}
\usepackage{booktabs}
"""


def convert(content: str, *, standalone: bool = True) -> str:
    """Convert Markdown *content* string to LaTeX.

    Parameters
    ----------
    content:
        Raw Markdown text.
    standalone:
        When ``True`` (default) wrap the body in a full LaTeX document
        (``\\documentclass`` … ``\\end{document}``).  When ``False``
        return only the converted body.
    """
    body = convert_body(content)
    if not standalone:
        return body
    return _PREAMBLE + "\n\\begin{document}\n\n" + body + "\n\n\\end{document}\n"


# ---------------------------------------------------------------------------
# File-level API
# ---------------------------------------------------------------------------

def convert_file(input_path: str, output_path: str | None = None, *, standalone: bool = True) -> str:
    """Convert *input_path* (``.md``) and write a ``.tex`` file.

    Returns the path of the output file.
    """
    if output_path is None:
        base, _ = os.path.splitext(input_path)
        output_path = base + ".tex"

    with open(input_path, encoding="utf-8") as fh:
        content = fh.read()

    tex = convert(content, standalone=standalone)

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(tex)

    return output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        print("Usage: md2tex.py <input.md> [output.tex]")
        print("Convert a Markdown file to well-formed LaTeX.")
        return 0

    input_path = argv[0]
    output_path = argv[1] if len(argv) > 1 else None

    if not os.path.isfile(input_path):
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        return 1

    out = convert_file(input_path, output_path)
    print(f"Converted: {input_path}  →  {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
