#!/usr/bin/env python3
"""md2tex: Convert Markdown files to well-formed LaTeX.

Supported input features:
- Block quotes (tab-indented lines or standard ``>`` prefix)
- Tables in HTML (``<table>``...``</table>``)
- Equations in Math TeX / LaTeX (``$...$``, ``$$...$$``, ``\\(...\\)``, ``\\[...\\]``)
- Figures in Markdown reference format pointing to a subdirectory
  (``![alt "Caption"](subdir/image.ext)``)
- Headings (``#`` … ``######``)
- Bold, italic, inline code, hyperlinks
- Fenced code blocks
- Unordered and ordered lists
- Horizontal rules
"""

import os
import re
import shutil
import struct
import subprocess
import sys
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# HTML table parser
# ---------------------------------------------------------------------------


class _TableParser(HTMLParser):
    """Collect rows/cells from a single HTML ``<table>`` block."""

    def __init__(self):
        super().__init__()
        self.rows = []  # list of (cells, is_header_flags)
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
        r"\adjustbox{max width=\columnwidth}{%",
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
            cell = _normalize_hyphens(cell)
            cell = _escape_ampersands(cell)
            cell = _escape_percents(cell)
            cell = _escape_underscores(cell)
            formatted.append(r"\textbf{" + cell + "}" if is_hdr else cell)
        lines.append(" & ".join(formatted) + r" \\")
        lines.append(r"\hline")

    lines += [r"\end{tabular}%", r"}", r"\end{table}"]
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


def _escape_percents(text: str) -> str:
    """Escape ``%`` as ``\\%`` outside math regions; leave ``\\%`` alone.

    An unescaped ``%`` starts a LaTeX comment that consumes the rest of the
    line, so e.g. a table cell containing ``196 (0.6%)`` would swallow its
    own row terminator and corrupt the alignment of every following row.
    """
    return _with_math_protected(text, lambda t: re.sub(r"(?<!\\)%", r"\\%", t))


def _escape_carets(text: str) -> str:
    """Escape ``^`` as ``\\^{}`` outside math regions; leave ``\\^`` alone.

    Outside math mode ``^`` is a reserved LaTeX character that triggers a
    "Missing $ inserted" error.  Inside math mode it is the superscript
    operator and must be left untouched.
    """
    return _with_math_protected(text, lambda t: re.sub(r"(?<!\\)\^", r"\\^{}", t))


def _escape_underscores(text: str) -> str:
    """Escape ``_`` as ``\\_`` outside math regions; leave ``\\_`` alone.

    Outside math mode ``_`` is a reserved LaTeX character (subscript) that
    triggers a "Missing $ inserted" error.  Common offenders are URLs and
    identifier-shaped strings that survived the inline pass — Markdown
    italic ``_word_`` has already been converted to ``\\textit{word}`` by
    the time this runs, so the only underscores left are literal ones.
    """
    return _with_math_protected(text, lambda t: re.sub(r"(?<!\\)_", r"\\_", t))


def _escape_currency_dollars(text: str) -> str:
    """Escape ``$`` followed by a digit (currency) as ``\\$``.

    Must run before any math-protection pass: the inline-math regex
    pairs ``$...$`` greedily, so ``$12 to $18`` would otherwise be
    stashed as a bogus math region and emitted to LaTeX as math mode.
    Skips ``\\$`` (already escaped) and ``$$`` (display-math open).
    """
    return re.sub(r"(?<!\\)(?<!\$)\$(?!\$)(?=\d)", r"\\$", text)


# Unicode characters that the standard `verbatim` environment can't render
# reliably (the typewriter font lacks glyphs for them under several common
# LaTeX setups).  Mapped to ASCII equivalents that read sensibly in monospace.
# Note: dash mappings here differ from the prose `_HYPHEN_MAP` below — inside
# verbatim, LaTeX's `--` / `---` ligatures don't fire, so en-dash collapses
# to `-` and em-dash to `--` (visual approximation) rather than `--` / `---`.
_VERBATIM_UNICODE_MAP = {
    # Dash/hyphen variants — keys use \u escapes since several are visually
    # indistinguishable from ASCII `-` (or, for U+00AD, invisible) in source.
    "\u2013": "-",  # EN DASH
    "\u2014": "--",  # EM DASH
    "\u2010": "-",  # HYPHEN
    "\u2011": "-",  # NON-BREAKING HYPHEN
    "\u2012": "--",  # FIGURE DASH
    "\u2015": "--",  # HORIZONTAL BAR
    "\u2212": "-",  # MINUS SIGN
    "\u00ad": "",  # SOFT HYPHEN (invisible; advisory — drop)
    "‘": "'",  # ‘ left single quote
    "’": "'",  # ’ right single quote
    "“": '"',  # “ left double quote
    "”": '"',  # ” right double quote
    "•": "*",  # • bullet
    "…": "...",  # … horizontal ellipsis
    " ": " ",  # NBSP
    **{
        _src: f"^{_dst}"
        for _src, _dst in {
            "⁰": "0",
            "¹": "1",
            "²": "2",
            "³": "3",
            "⁴": "4",
            "⁵": "5",
            "⁶": "6",
            "⁷": "7",
            "⁸": "8",
            "⁹": "9",
            "⁺": "+",
            "⁻": "-",
            "⁼": "=",
            "⁽": "(",
            "⁾": ")",
            "ⁿ": "n",
        }.items()
    },
}


# Unicode superscript characters → ASCII counterparts.  Used to build
# $^{...}$ runs in regular prose; the verbatim map above covers the
# verbatim case (where $...$ doesn't apply).
_SUPERSCRIPT_MAP = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁺": "+",
    "⁻": "-",
    "⁼": "=",
    "⁽": "(",
    "⁾": ")",
    "ⁿ": "n",
}

_SUPERSCRIPT_RUN_RE = re.compile("[" + "".join(_SUPERSCRIPT_MAP) + "]+")


def _convert_superscripts(text: str) -> str:
    """Convert runs of Unicode superscript chars (e.g. ``²``) to ``$^{...}$``."""

    def _repl(m: re.Match) -> str:
        ascii_run = "".join(_SUPERSCRIPT_MAP[c] for c in m.group(0))
        return f"$^{ascii_run}$" if len(ascii_run) == 1 else f"$^{{{ascii_run}}}$"

    return _with_math_protected(text, lambda t: _SUPERSCRIPT_RUN_RE.sub(_repl, t))


def _sanitize_verbatim(line: str) -> str:
    """Replace Unicode characters that misrender inside ``verbatim``."""
    for src, dst in _VERBATIM_UNICODE_MAP.items():
        if src in line:
            line = line.replace(src, dst)
    return line


# Canonical LaTeX forms for Unicode hyphen/dash variants in regular prose.
# LaTeX composes ASCII hyphen-minus runs into the proper glyphs (`-` → hyphen,
# `--` → en-dash, `---` → em-dash), so we collapse Unicode variants to match.
_HYPHEN_MAP = {
    "\u2010": "-",  # HYPHEN
    "\u2011": "-",  # NON-BREAKING HYPHEN
    "\u2012": "--",  # FIGURE DASH
    "\u2013": "--",  # EN DASH
    "\u2014": "---",  # EM DASH
    "\u2015": "---",  # HORIZONTAL BAR
    "\u2212": "-",  # MINUS SIGN
    "\u00ad": "",  # SOFT HYPHEN (advisory; drop)
}


def _normalize_hyphens(text: str) -> str:
    """Collapse Unicode hyphen/dash variants to LaTeX-canonical -, --, ---."""

    def _do(t: str) -> str:
        for src, dst in _HYPHEN_MAP.items():
            if src in t:
                t = t.replace(src, dst)
        return t

    return _with_math_protected(text, _do)


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
# E-ink image preprocessing
# ---------------------------------------------------------------------------

# Raster formats we'll convert.  Vector/PDF/SVG are skipped — adaptive
# thresholding doesn't apply meaningfully and rasterizing them here would be
# surprising.
_EINK_RASTER_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".gif"}

# Histogram clip points (percent) for the post-normalize levels stretch.
# Pixels darker than the low point go fully black; lighter than the high point
# go fully white.  Keeps the extremes punchy without crushing midtones.
_EINK_LEVEL_LOW = 5
_EINK_LEVEL_HIGH = 95

# Mid-tone gamma applied between those clip points.  >1.0 brightens the mids,
# which compensates for e-ink panels reading slightly darker than the source
# (rM Carta in particular).  Portraits and engravings keep their detail this
# way instead of getting binarized into blobs.
_EINK_LEVEL_GAMMA = 1.2


def _eink_tool() -> tuple[list[str], str] | None:
    """Return ``(command, flavor)`` for image processing, or ``None``.

    *flavor* is ``"im"`` (ImageMagick) or ``"gm"`` (GraphicsMagick).
    The pipeline itself is portable across both, but the flavor is still
    useful for callers that need to invoke ``identify`` or other companion
    tools with the right invocation form.
    """
    if shutil.which("magick"):
        return ["magick"], "im"
    if shutil.which("gm"):
        return ["gm", "convert"], "gm"
    if shutil.which("convert"):
        # `convert` could be either IM (still common) or GM's compatibility
        # shim.  Probe its banner.
        try:
            out = subprocess.run(
                ["convert", "-version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ["convert"], "im"
        flavor = "gm" if "GraphicsMagick" in out else "im"
        return ["convert"], flavor
    return None


def _eink_output_path(rel_path: str) -> str:
    """Return the relative path of the processed image for *rel_path*."""
    return os.path.splitext(rel_path)[0] + ".eink.png"


def _process_image_for_eink(rel_path: str, base_dir: str) -> str:
    """Generate a contrast-enhanced grayscale copy and return its relative path.

    Pipeline: convert to grayscale, normalize the histogram, then apply a
    levels stretch with a brightening gamma.  This preserves midtone detail
    (faces, engraved shading, line weight) far better than hard binarization
    while still giving e-ink panels the punchy black-and-white range they
    need to read clearly — reMarkable and similar devices dither the result
    onto their 16-level gray panel themselves.

    The processed file is cached next to the original and only regenerated
    when the source is newer.  Returns *rel_path* unchanged when the source
    is missing, the format is unsupported, or no image tool is on PATH.
    """
    ext = os.path.splitext(rel_path)[1].lower()
    if ext not in _EINK_RASTER_EXTS:
        return rel_path

    abs_src = rel_path if os.path.isabs(rel_path) else os.path.join(base_dir, rel_path)
    if not os.path.isfile(abs_src):
        return rel_path

    out_rel = _eink_output_path(rel_path)
    abs_out = out_rel if os.path.isabs(out_rel) else os.path.join(base_dir, out_rel)

    if os.path.isfile(abs_out) and os.path.getmtime(abs_out) >= os.path.getmtime(
        abs_src
    ):
        return out_rel

    detected = _eink_tool()
    if detected is None:
        return rel_path

    tool, _flavor = detected
    # The 3-arg "black,gamma,white" form of -level is required for
    # GraphicsMagick compatibility — its 2-arg form means "black,gamma"
    # rather than "black,white" as in ImageMagick.
    level_arg = f"{_EINK_LEVEL_LOW}%,{_EINK_LEVEL_GAMMA},{_EINK_LEVEL_HIGH}%"

    cmd = tool + [
        abs_src,
        "-colorspace",
        "Gray",
        "-normalize",
        "-level",
        level_arg,
        abs_out,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return rel_path
    return out_rel


# Same shape as the figure regex in _convert_inline; kept separate so the
# pre-pass can rewrite paths without invoking the full inline conversion.
_IMAGE_REF_RE = re.compile(r'!\[([^\]]*)\]\(([^)"]+?)(?:\s+"([^"]*)")?\)')


def _preprocess_eink_images(content: str, base_dir: str) -> str:
    """Rewrite Markdown image refs to point at e-ink-processed copies."""

    def _repl(m: re.Match) -> str:
        alt = m.group(1)
        path = m.group(2).strip()
        caption = m.group(3)
        new_path = _process_image_for_eink(path, base_dir)
        caption_part = f' "{caption}"' if caption is not None else ""
        return f"![{alt}]({new_path}{caption_part})"

    return _IMAGE_REF_RE.sub(_repl, content)


# ---------------------------------------------------------------------------
# Inline Markdown → LaTeX conversion
# ---------------------------------------------------------------------------


def _image_dimensions(abs_path: str) -> tuple[int, int] | None:
    """Return ``(width, height)`` for *abs_path* by reading the file header.

    Stdlib-only; supports PNG, GIF, BMP, and JPEG. Other formats (PDF, SVG,
    WebP, TIFF, …) and unreadable files return ``None`` — callers should
    fall back to a default width factor in that case.
    """
    try:
        with open(abs_path, "rb") as fh:
            head = fh.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                w, h = struct.unpack(">II", head[16:24])
                return w, h
            if head[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", head[6:10])
                return w, h
            if head[:2] == b"BM":
                w, h = struct.unpack("<ii", head[18:26])
                return abs(w), abs(h)
            if head[:2] == b"\xff\xd8":
                fh.seek(2)
                while True:
                    byte = fh.read(1)
                    while byte and byte != b"\xff":
                        byte = fh.read(1)
                    while byte == b"\xff":
                        byte = fh.read(1)
                    if not byte:
                        return None
                    marker = byte[0]
                    # Stand-alone markers carry no payload.
                    if marker == 0x01 or 0xD0 <= marker <= 0xD9:
                        continue
                    seg_len_bytes = fh.read(2)
                    if len(seg_len_bytes) < 2:
                        return None
                    seg_len = struct.unpack(">H", seg_len_bytes)[0]
                    # SOFn frames hold the dimensions; skip DHT/JPG/DAC.
                    if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                        fh.read(1)  # sample precision
                        h, w = struct.unpack(">HH", fh.read(4))
                        return w, h
                    fh.read(seg_len - 2)
    except (OSError, struct.error):
        return None
    return None


def _figure_width_factor(path: str, base_dir: str) -> str:
    """Return LaTeX width multiplier for an image: ``0.7`` if landscape, ``0.5`` else.

    "Landscape" means width > height. Square or portrait images, plus any
    image whose dimensions can't be read (missing file, unsupported format),
    fall to ``0.5`` — the safer default for fitting within a column.
    """
    abs_path = path if os.path.isabs(path) else os.path.join(base_dir, path)
    dims = _image_dimensions(abs_path)
    if dims is None:
        return "0.5"
    w, h = dims
    return "0.7" if w > h else "0.5"


def _make_figure_repl(base_dir: str):
    """Build a regex replacement closure for Markdown figures with *base_dir*."""

    def _figure_repl(m: re.Match) -> str:
        alt = m.group(1)
        path = m.group(2).strip()
        caption = m.group(3).strip() if m.group(3) else alt
        basename = os.path.splitext(os.path.basename(path))[0]
        label = re.sub(r"[^a-zA-Z0-9]+", "", basename).lower()
        width = _figure_width_factor(path, base_dir)
        return (
            "\n"
            r"\begin{figure}[htbp]" + "\n"
            r"\centering" + "\n"
            r"\includegraphics[width=" + width + r"\columnwidth]{" + path + "}\n"
            r"\caption{" + caption + "}\n"
            r"\label{fig:" + label + "}\n"
            r"\end{figure}" + "\n"
        )

    return _figure_repl


def _convert_inline(text: str, base_dir: str = ".") -> str:
    """Apply inline Markdown → LaTeX substitutions to *text*."""
    # Escape currency $ first — before anything that protects math regions,
    # because the math-pairing regex would otherwise mis-pair currency $.
    text = _escape_currency_dollars(text)
    # Figures: ![alt](path "caption") or ![alt](path)
    text = re.sub(
        r'!\[([^\]]*)\]\(([^)"]+?)(?:\s+"([^"]*)")?\)',
        _make_figure_repl(base_dir),
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
    # Unicode hyphen/dash variants → -, --, ---
    text = _normalize_hyphens(text)
    # Unicode superscripts (¹²³…) → $^{...}$
    text = _convert_superscripts(text)
    # Escape stray ampersands (preserves math regions and existing \&)
    text = _escape_ampersands(text)
    # Escape stray percent signs (preserves math regions and existing \%)
    text = _escape_percents(text)
    # Escape stray carets (preserves math regions and existing \^)
    text = _escape_carets(text)
    # Escape stray underscores (preserves math regions and existing \_).
    # Must run after italic _word_ has been converted to \textit{word}.
    text = _escape_underscores(text)
    return text


# ---------------------------------------------------------------------------
# Block-level conversion state machine
# ---------------------------------------------------------------------------


def _to_title_case(text: str) -> str:
    """Convert ALL-CAPS *text* to Title Case (each word capitalized).

    Operates on letter runs (apostrophes count as part of the word so
    ``DON'T`` becomes ``Don't``). Punctuation, digits, and whitespace are
    untouched. Intended for ALL-CAPS prose where the original casing is
    already lost — acronyms like ``URL`` will flatten to ``Url``, which is
    acceptable in that context and avoids hbox/overfull issues for headings.
    """

    def _cap(m: re.Match) -> str:
        word = m.group(0)
        return word[0].upper() + word[1:].lower()

    return re.sub(r"[A-Za-z][A-Za-z']*", _cap, text)


def _is_all_caps_heading(line: str) -> bool:
    """True when *line* looks like an ALL-CAPS subsection heading.

    Requires at least two alphabetic characters and no lowercase letters.
    Punctuation, digits, apostrophes, and spaces are allowed; a blank line
    or letter-free line returns False.
    """
    stripped = line.strip()
    if not stripped:
        return False
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) < 2:
        return False
    return all(c.isupper() for c in letters)


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


# ---------------------------------------------------------------------------
# Index section post-processor
# ---------------------------------------------------------------------------

# An ``Index`` heading at any sectioning level (\section, \subsection, …) opens
# index mode; the next sectioning command at any level closes it.
_INDEX_HEADING_RE = re.compile(
    r"^\\(?:sub)*(?:section|paragraph)\*?\{Index\}\s*$"
)
_LATEX_HEADING_RE = re.compile(r"^\\(?:sub)*(?:section|paragraph)\*?\{")

# Markdown-level recognition of an ``INDEX`` heading — either ALL-CAPS on
# its own line (the form OCR usually produces) or a Markdown ATX heading.
_INDEX_MD_HEADING_RE = re.compile(r"^(?:#{1,6}\s+)?index\s*$", re.IGNORECASE)
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+\S")

# Sentinel placed at the start of each indented sub-entry by the markdown
# pre-pass.  HTML-comment-shaped so it survives ``_convert_inline`` (no
# Markdown-active characters) and is trivial to detect at the post-pass.
_INDEX_SUB_TOKEN = "<!--idxsub-->"

# A line is an index entry if it ends with a page reference (digit, optionally
# followed by digits / dashes / commas / periods / semicolons / spaces — so
# "656", "614--21", "692.", "366--69, 728" all qualify) or contains a
# cross-reference (``see X``).  Both cues miss the explanatory paragraph at
# the top of an index ("Page numbers in italics …"), which ends with letters.
_INDEX_PAGEREF_RE = re.compile(r"\d[\d\s.,;\-]*$")
_INDEX_SEE_RE = re.compile(r"(?:^|[,;])\s*see\s+(?:also\s+)?[A-Za-z]")


def _preprocess_index_indents(content: str) -> str:
    """Within an ``INDEX`` section, strip leading whitespace from lines and
    mark formerly-indented lines as sub-entries.

    Two things this fixes at once:

    1. md2tex's block-quote rule treats any line starting with a tab or
       four spaces as ``verbatim``.  Inside an index that misfires on
       sub-entries that the OCR happened to preserve indented, dropping
       chunks of the index into typewriter-font verbatim blocks.
    2. Where the OCR did preserve indentation, that's a far more reliable
       sub-entry signal than any first-character heuristic — keeping it
       lets the post-pass render real two-level structure for those lines.
    """
    lines = content.split("\n")
    out: list[str] = []
    in_section = False
    for line in lines:
        if _INDEX_MD_HEADING_RE.match(line.strip()):
            in_section = True
            out.append(line)
            continue
        # Any non-INDEX Markdown heading inside the section closes it.
        if in_section and _MD_HEADING_RE.match(line) and not _INDEX_MD_HEADING_RE.match(
            line.strip()
        ):
            in_section = False
            out.append(line)
            continue
        if in_section and re.match(r"^(\t| {2,})\S", line):
            out.append(_INDEX_SUB_TOKEN + line.lstrip())
            continue
        out.append(line)
    return "\n".join(out)


def _looks_like_index_entry(line: str) -> bool:
    # Trailing ``:`` — main entry that introduces a sub-entry block (e.g.
    # "African Americans:") — has neither page refs nor a ``see`` cue, so
    # it needs its own clause or it merges into the next paragraph.
    if line.endswith(":"):
        return True
    return bool(_INDEX_PAGEREF_RE.search(line) or _INDEX_SEE_RE.search(line))


def _post_process_index(body: str) -> str:
    """Reformat lines under an ``Index`` heading as hanging-indent entries.

    Without this pass every entry collapses into one flowing paragraph in
    the PDF: the source markdown puts each entry on its own line but with
    no blank lines between them, so LaTeX joins them.  We wrap entry-shaped
    lines in ``\\hangindent`` paragraphs so the entry starts at the margin
    and any wrap lines indent under it.

    Lines marked by the markdown pre-pass with ``_INDEX_SUB_TOKEN`` (those
    that were indented in the source) render as sub-entries — indented one
    em with a deeper hanging continuation.  Lines without the marker stay
    at the main-entry level; we don't guess sub-entries from line content
    alone, since no first-character rule survives lowercase main entries
    ("abolition") or proper-noun-led sub-entries.

    Verbatim regions are passed through untouched — emitting ``\\hangindent``
    inside ``\\begin{verbatim}`` would render the LaTeX commands as literal
    text in the PDF.
    """
    lines = body.split("\n")
    out: list[str] = []
    in_section = False  # under an Index heading
    in_block = False  # currently emitting hanging-indent entries
    in_verbatim = False  # inside a \begin{verbatim} … \end{verbatim} block

    def _close_block() -> None:
        nonlocal in_block
        if in_block:
            out.append(r"\endgroup")
            in_block = False

    for line in lines:
        stripped = line.strip()

        # Verbatim passthrough — no rewriting inside a verbatim block.
        if in_verbatim:
            out.append(line)
            if stripped == r"\end{verbatim}":
                in_verbatim = False
            continue
        if stripped == r"\begin{verbatim}":
            _close_block()
            out.append(line)
            in_verbatim = True
            continue

        if _INDEX_HEADING_RE.match(stripped):
            _close_block()
            out.append(line)
            in_section = True
            continue

        if in_section and _LATEX_HEADING_RE.match(stripped):
            _close_block()
            out.append(line)
            in_section = False
            continue

        if in_section and (
            stripped.startswith(_INDEX_SUB_TOKEN)
            or _looks_like_index_entry(stripped)
        ):
            if not in_block:
                out.append(r"\begingroup")
                out.append(r"\setlength{\parindent}{0pt}")
                out.append(r"\setlength{\parskip}{0pt}")
                in_block = True
            if stripped.startswith(_INDEX_SUB_TOKEN):
                payload = stripped[len(_INDEX_SUB_TOKEN):].lstrip()
                out.append(
                    r"\hangindent=2em\hangafter=1\noindent\hspace*{1em}"
                    + payload
                    + r"\par"
                )
            else:
                out.append(
                    r"\hangindent=1em\hangafter=1\noindent " + stripped + r"\par"
                )
            continue

        # Non-entry content inside the section (e.g. the leading explainer
        # paragraph, or a blank line). Pass it through unchanged, but close
        # any open entry block first so the following entries restart it.
        if in_section and stripped:
            _close_block()
        out.append(line)

    _close_block()
    return "\n".join(out)


def convert_body(content: str, base_dir: str = ".") -> str:
    """Convert Markdown *content* to a LaTeX body (no document wrapper).

    *base_dir* is used to resolve relative figure paths so that image
    dimensions can be inspected for choosing a per-figure width factor.
    """
    lines = content.splitlines()
    result: list[str] = []
    state = {
        "in_code_block": False,
        "in_html_table": False,
        "in_itemize": False,
        "in_enumerate": False,
        "in_quote": False,
        "in_display_math": None,  # None or the closing delimiter ('$$' / '\\]')
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
            result.append(f"\\{cmd}{{{_convert_inline(title, base_dir)}}}")
            i += 1
            continue

        # ------------------------------------------------------------------ #
        # ALL-CAPS subsection heading — one or more consecutive all-caps      #
        # lines collapse into a single \subsection*{...}.                      #
        # ------------------------------------------------------------------ #
        if _is_all_caps_heading(line):
            caps_lines = [line.strip()]
            j = i + 1
            while j < len(lines) and _is_all_caps_heading(lines[j]):
                caps_lines.append(lines[j].strip())
                j += 1
            _close_list(result, state)
            title = _to_title_case(" ".join(caps_lines))
            result.append(r"\subsection*{" + _convert_inline(title, base_dir) + "}")
            i = j
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
            result.append(r"  \item " + _convert_inline(ul.group(2), base_dir))
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
            result.append(r"  \item " + _convert_inline(ol.group(2), base_dir))
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
        result.append(_convert_inline(line, base_dir))
        i += 1

    # Close any environments still open at end of file.
    _close_list(result, state)
    _close_quote(result, state)
    if state["in_code_block"]:
        result.append(r"\end{verbatim}")

    return _post_process_index("\n".join(result))


# ---------------------------------------------------------------------------
# Document wrapper
# ---------------------------------------------------------------------------

_PREAMBLE = r"""\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath}
\usepackage{graphicx}
\usepackage{hyperref}
\usepackage{booktabs}
\usepackage{adjustbox}
\usepackage{microtype}
\emergencystretch=3em
\tolerance=1000
"""


def convert(
    content: str,
    *,
    standalone: bool = True,
    eink: bool = False,
    base_dir: str = ".",
) -> str:
    """Convert Markdown *content* string to LaTeX.

    Parameters
    ----------
    content:
        Raw Markdown text.
    standalone:
        When ``True`` (default) wrap the body in a full LaTeX document
        (``\\documentclass`` … ``\\end{document}``).  When ``False``
        return only the converted body.
    eink:
        When ``True`` rewrite raster image references to point at
        contrast-enhanced grayscale copies (``<name>.eink.png``) suitable
        for e-ink displays.  Requires ``magick``, ``convert``, or ``gm``
        on PATH; silently no-ops on missing tools or files.
    base_dir:
        Directory used to resolve relative image paths — both for the
        optional ``eink`` rewrite pass and for inspecting figure dimensions
        to pick a width factor in the LaTeX output.
    """
    if eink:
        content = _preprocess_eink_images(content, base_dir)
    content = _preprocess_index_indents(content)
    body = convert_body(content, base_dir)
    # Defensive: drop any stray sub-entry markers that didn't get consumed
    # by the post-pass (e.g. a marked line that fell outside an Index
    # section, or whose section heading the post-pass didn't recognise).
    body = body.replace(_INDEX_SUB_TOKEN, "")
    if not standalone:
        return body
    return _PREAMBLE + "\n\\begin{document}\n\n" + body + "\n\n\\end{document}\n"


# ---------------------------------------------------------------------------
# File-level API
# ---------------------------------------------------------------------------


def convert_file(
    input_path: str,
    output_path: str | None = None,
    *,
    standalone: bool = True,
    eink: bool = False,
) -> str:
    """Convert *input_path* (``.md``) and write a ``.tex`` file.

    Returns the path of the output file.
    """
    if output_path is None:
        base, _ = os.path.splitext(input_path)
        output_path = base + ".tex"

    with open(input_path, encoding="utf-8") as fh:
        content = fh.read()

    base_dir = os.path.dirname(os.path.abspath(input_path))
    tex = convert(content, standalone=standalone, eink=eink, base_dir=base_dir)

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
        print("Usage: md2tex.py [--eink] <input.md> [output.tex]")
        print("Convert a Markdown file to well-formed LaTeX.")
        print("  --eink   Preprocess raster images into contrast-enhanced")
        print("           grayscale copies for legibility on e-ink displays.")
        return 0

    eink = False
    positional: list[str] = []
    for arg in argv:
        if arg == "--eink":
            eink = True
        else:
            positional.append(arg)

    if not positional:
        print("Error: no input file given", file=sys.stderr)
        return 1

    input_path = positional[0]
    output_path = positional[1] if len(positional) > 1 else None

    if not os.path.isfile(input_path):
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        return 1

    if eink and _eink_tool() is None:
        print(
            "Warning: --eink requested but no image tool found on PATH "
            "(looked for magick, convert, gm). Image refs left unchanged.",
            file=sys.stderr,
        )

    out = convert_file(input_path, output_path, eink=eink)
    print(f"Converted: {input_path}  →  {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
