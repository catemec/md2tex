"""Tests for md2tex.py — Markdown to LaTeX converter."""

import os
import struct
import subprocess
import sys
import textwrap
import zlib

import pytest

import md2tex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def body(md: str) -> str:
    """Return the LaTeX body (no preamble) for a Markdown string."""
    return md2tex.convert(md, standalone=False)


# ---------------------------------------------------------------------------
# Block quotes
# ---------------------------------------------------------------------------

class TestBlockQuotes:
    def test_tab_indented_single_line(self):
        md = "\tThis is a block quote.\n"
        result = body(md)
        assert r"\begin{verbatim}" in result
        assert "This is a block quote." in result
        assert r"\end{verbatim}" in result

    def test_tab_indented_multi_line_preserves_newlines(self):
        md = "\tFirst line.\n\tSecond line.\n"
        result = body(md)
        # Single verbatim block, with the two lines on separate lines.
        assert result.count(r"\begin{verbatim}") == 1
        assert result.count(r"\end{verbatim}") == 1
        assert "First line.\nSecond line." in result

    def test_four_space_indented(self):
        md = "    Indented with four spaces.\n"
        result = body(md)
        assert r"\begin{verbatim}" in result
        assert "Indented with four spaces." in result
        assert r"\end{verbatim}" in result

    def test_standard_prefix(self):
        md = "> A quoted line.\n"
        result = body(md)
        assert r"\begin{verbatim}" in result
        assert "A quoted line." in result
        assert r"\end{verbatim}" in result

    def test_standard_prefix_multi_line_preserves_newlines(self):
        md = "> Line one.\n> Line two.\n"
        result = body(md)
        assert result.count(r"\begin{verbatim}") == 1
        assert "Line one.\nLine two." in result

    def test_quote_content_not_inline_processed(self):
        # Verbatim should not transform markdown emphasis inside the quote.
        md = "> **stays bold-source**\n"
        result = body(md)
        assert "**stays bold-source**" in result
        assert r"\textbf" not in result

    def test_quote_closed_before_heading(self):
        md = "> Quote text.\n\n# Heading\n"
        result = body(md)
        # The quote must be closed before the heading command.
        quote_end = result.index(r"\end{verbatim}")
        section_start = result.index(r"\section")
        assert quote_end < section_start


# ---------------------------------------------------------------------------
# HTML tables
# ---------------------------------------------------------------------------

class TestHTMLTables:
    def test_simple_table(self):
        md = textwrap.dedent("""\
            <table>
            <tr><th>Name</th><th>Age</th></tr>
            <tr><td>Alice</td><td>30</td></tr>
            </table>
        """)
        result = body(md)
        assert r"\begin{table}" in result
        assert r"\begin{tabular}" in result
        assert r"\end{tabular}" in result
        assert r"\end{table}" in result

    def test_header_cells_bold(self):
        md = "<table>\n<tr><th>Header</th></tr>\n<tr><td>Cell</td></tr>\n</table>\n"
        result = body(md)
        assert r"\textbf{Header}" in result
        assert "Cell" in result

    def test_hline_present(self):
        md = "<table>\n<tr><th>A</th><th>B</th></tr>\n<tr><td>1</td><td>2</td></tr>\n</table>\n"
        result = body(md)
        assert r"\hline" in result

    def test_ampersand_column_separator(self):
        md = "<table>\n<tr><td>X</td><td>Y</td></tr>\n</table>\n"
        result = body(md)
        assert " & " in result

    def test_capped_at_columnwidth(self):
        md = "<table>\n<tr><td>X</td><td>Y</td></tr>\n</table>\n"
        result = body(md)
        # Tabular is wrapped in \adjustbox so over-wide tables shrink, but
        # narrow tables are not stretched.
        assert r"\adjustbox{max width=\columnwidth}{" in result
        ab = result.index(r"\adjustbox{max width=\columnwidth}{")
        tab_begin = result.index(r"\begin{tabular}")
        tab_end = result.index(r"\end{tabular}")
        assert ab < tab_begin < tab_end

    def test_adjustbox_package_in_preamble(self):
        result = md2tex.convert("Hello\n", standalone=True)
        assert r"\usepackage{adjustbox}" in result

    def test_multi_column(self):
        md = textwrap.dedent("""\
            <table>
            <tr><th>Col1</th><th>Col2</th><th>Col3</th></tr>
            <tr><td>A</td><td>B</td><td>C</td></tr>
            </table>
        """)
        result = body(md)
        # Three columns → two "&" per data row
        assert result.count(" & ") >= 2


# ---------------------------------------------------------------------------
# Equations
# ---------------------------------------------------------------------------

class TestEquations:
    def test_inline_math_preserved(self):
        md = "The formula is $x^2 + y^2 = z^2$.\n"
        result = body(md)
        assert "$x^2 + y^2 = z^2$" in result

    def test_display_math_preserved(self):
        md = "$$\n\\int_0^\\infty e^{-x} dx = 1\n$$\n"
        result = body(md)
        assert "$$" in result
        assert r"\int_0^\infty" in result

    def test_latex_display_math_preserved(self):
        md = r"\[" + "\n  E = mc^2\n" + r"\]" + "\n"
        result = body(md)
        assert r"\[" in result
        assert "E = mc^2" in result

    def test_inline_math_in_sentence(self):
        md = "The value $\\alpha$ is important.\n"
        result = body(md)
        assert "$\\alpha$" in result


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

class TestFigures:
    def test_figure_with_caption(self):
        md = '![Alt text](images/fig01.png "My Caption")\n'
        result = body(md)
        assert r"\begin{figure}" in result
        assert r"\centering" in result
        assert r"\includegraphics[width=\columnwidth]{images/fig01.png}" in result
        assert r"\caption{My Caption}" in result
        assert r"\label{fig:fig01}" in result
        assert r"\end{figure}" in result

    def test_figure_without_caption_uses_alt(self):
        md = "![Diagram](images/diagram.png)\n"
        result = body(md)
        assert r"\includegraphics[width=\columnwidth]{images/diagram.png}" in result
        assert r"\caption{Diagram}" in result
        assert r"\label{fig:diagram}" in result

    def test_figure_subdirectory_path(self):
        md = "![Graph](figures/chapter1/graph.pdf)\n"
        result = body(md)
        assert r"\includegraphics[width=\columnwidth]{figures/chapter1/graph.pdf}" in result
        assert r"\label{fig:graph}" in result

    def test_figure_environment_tags(self):
        md = '![X](imgs/x.png "Caption X")\n'
        result = body(md)
        assert r"\begin{figure}[htbp]" in result
        assert r"\end{figure}" in result


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------

class TestHeadings:
    def test_h1(self):
        assert r"\section{Title}" in body("# Title\n")

    def test_h2(self):
        assert r"\subsection{Title}" in body("## Title\n")

    def test_h3(self):
        assert r"\subsubsection{Title}" in body("### Title\n")

    def test_h4(self):
        assert r"\paragraph{Title}" in body("#### Title\n")


# ---------------------------------------------------------------------------
# Inline formatting
# ---------------------------------------------------------------------------

class TestInlineFormatting:
    def test_bold_asterisks(self):
        assert r"\textbf{word}" in body("**word**\n")

    def test_bold_underscores(self):
        assert r"\textbf{word}" in body("__word__\n")

    def test_italic_asterisks(self):
        assert r"\textit{word}" in body("*word*\n")

    def test_italic_underscores(self):
        assert r"\textit{word}" in body("_word_\n")

    def test_inline_code(self):
        assert r"\texttt{code}" in body("`code`\n")

    def test_hyperlink(self):
        result = body("[click here](https://example.com)\n")
        assert r"\href{https://example.com}{click here}" in result


# ---------------------------------------------------------------------------
# Verbatim Unicode sanitization
# ---------------------------------------------------------------------------

class TestVerbatimSanitization:
    def test_endash_in_blockquote_replaced(self):
        md = "> South Carolina, 1716–1807\n"
        result = body(md)
        assert "1716-1807" in result
        assert "1716–1807" not in result

    def test_emdash_in_blockquote_replaced(self):
        md = "> Like this — really\n"
        result = body(md)
        assert "Like this -- really" in result
        assert "—" not in result

    def test_smart_quotes_in_blockquote_replaced(self):
        md = "> Pollitzer’s “Studies”\n"
        result = body(md)
        assert "Pollitzer's \"Studies\"" in result
        assert "’" not in result and "“" not in result

    def test_bullet_in_blockquote_replaced(self):
        md = "> intro • point one\n"
        result = body(md)
        assert "intro * point one" in result

    def test_endash_in_code_block_replaced(self):
        md = "```\nrange 1-2 vs 1–2\n```\n"
        result = body(md)
        assert "range 1-2 vs 1-2" in result
        assert "–" not in result

    def test_endash_outside_verbatim_unchanged(self):
        # Plain prose should keep en-dash; preamble fontenc handles rendering.
        md = "Years 1716–1807 spanned a century.\n"
        result = body(md)
        assert "1716–1807" in result


# ---------------------------------------------------------------------------
# Preamble
# ---------------------------------------------------------------------------

class TestPreambleEncoding:
    def test_inputenc_utf8(self):
        result = md2tex.convert("Hello\n", standalone=True)
        assert r"\usepackage[utf8]{inputenc}" in result

    def test_fontenc_t1(self):
        result = md2tex.convert("Hello\n", standalone=True)
        assert r"\usepackage[T1]{fontenc}" in result


# ---------------------------------------------------------------------------
# Quote normalization
# ---------------------------------------------------------------------------

class TestQuoteNormalization:
    def test_double_quoted_word(self):
        result = body('He said "hello" to me.\n')
        assert "``hello''" in result

    def test_double_quote_at_start_of_line(self):
        result = body('"Open" first.\n')
        assert "``Open''" in result

    def test_unicode_smart_double_quotes(self):
        result = body("She said “hi” back.\n")
        assert "``hi''" in result

    def test_unicode_smart_single_quotes(self):
        result = body("It’s a ‘test’.\n")
        assert "It's a `test'" in result

    def test_quotes_in_math_preserved(self):
        # ASCII " inside $...$ shouldn't be normalized.
        result = body('Inline $a = "x"$ end.\n')
        assert '$a = "x"$' in result

    def test_apostrophe_left_alone(self):
        # ASCII ' is intentionally untouched (works as apostrophe).
        result = body("don't\n")
        assert "don't" in result


# ---------------------------------------------------------------------------
# Ampersand escaping
# ---------------------------------------------------------------------------

class TestAmpersandEscaping:
    def test_plain_ampersand_in_paragraph(self):
        assert r"AT\&T" in body("AT&T\n")

    def test_already_escaped_ampersand_unchanged(self):
        # Existing \& should not become \\&.
        result = body(r"AT\&T" + "\n")
        assert r"AT\&T" in result
        assert r"\\&" not in result

    def test_multiple_ampersands(self):
        result = body("Tom & Jerry & Spike\n")
        assert r"Tom \& Jerry \& Spike" in result

    def test_ampersand_in_inline_math_preserved(self):
        # Inline math may contain & (e.g., a small matrix); leave it alone.
        result = body(r"Inline $\begin{matrix}a & b\end{matrix}$ here." + "\n")
        assert r"$\begin{matrix}a & b\end{matrix}$" in result

    def test_ampersand_in_display_math_preserved(self):
        md = "$$\nx & y\n$$\n"
        result = body(md)
        assert "x & y" in result
        assert r"x \& y" not in result

    def test_ampersand_outside_math_escaped_when_math_present(self):
        result = body("Cats & dogs and $a + b$ and Tom & Jerry\n")
        assert r"Cats \& dogs" in result
        assert r"Tom \& Jerry" in result
        assert "$a + b$" in result

    def test_ampersand_in_url_escaped(self):
        result = body("[link](https://x.test/?a=1&b=2)\n")
        assert r"\href{https://x.test/?a=1\&b=2}{link}" in result

    def test_html_table_cell_ampersand_escaped(self):
        md = "<table>\n<tr><td>Tom & Jerry</td><td>OK</td></tr>\n</table>\n"
        result = body(md)
        # Cell content has \&, but the column separator " & " remains.
        assert r"Tom \& Jerry" in result
        assert " & OK" in result

    def test_html_entity_ampersand_in_table_cell(self):
        md = "<table>\n<tr><td>A&amp;B</td></tr>\n</table>\n"
        result = body(md)
        assert r"A\&B" in result


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

class TestLists:
    def test_unordered_list(self):
        md = "- Alpha\n- Beta\n- Gamma\n"
        result = body(md)
        assert r"\begin{itemize}" in result
        assert r"\end{itemize}" in result
        assert r"  \item Alpha" in result

    def test_ordered_list(self):
        md = "1. First\n2. Second\n3. Third\n"
        result = body(md)
        assert r"\begin{enumerate}" in result
        assert r"\end{enumerate}" in result
        assert r"  \item First" in result

    def test_list_closed_before_heading(self):
        md = "- Item\n\n# Section\n"
        result = body(md)
        itemize_end = result.index(r"\end{itemize}")
        section_start = result.index(r"\section")
        assert itemize_end < section_start


# ---------------------------------------------------------------------------
# Code blocks
# ---------------------------------------------------------------------------

class TestCodeBlocks:
    def test_fenced_code_block(self):
        md = "```python\nprint('hi')\n```\n"
        result = body(md)
        assert r"\begin{verbatim}" in result
        assert "print('hi')" in result
        assert r"\end{verbatim}" in result

    def test_code_not_processed_for_inline(self):
        md = "```\n**not bold**\n```\n"
        result = body(md)
        assert "**not bold**" in result


# ---------------------------------------------------------------------------
# Horizontal rule
# ---------------------------------------------------------------------------

class TestHorizontalRule:
    def test_dash_rule(self):
        assert r"\hrule" in body("---\n")

    def test_star_rule(self):
        assert r"\hrule" in body("***\n")


# ---------------------------------------------------------------------------
# Standalone document wrapper
# ---------------------------------------------------------------------------

class TestStandaloneDocument:
    def test_has_documentclass(self):
        result = md2tex.convert("Hello\n", standalone=True)
        assert r"\documentclass" in result

    def test_has_begin_document(self):
        result = md2tex.convert("Hello\n", standalone=True)
        assert r"\begin{document}" in result

    def test_has_end_document(self):
        result = md2tex.convert("Hello\n", standalone=True)
        assert r"\end{document}" in result

    def test_has_amsmath(self):
        result = md2tex.convert("Hello\n", standalone=True)
        assert r"\usepackage{amsmath}" in result

    def test_has_graphicx(self):
        result = md2tex.convert("Hello\n", standalone=True)
        assert r"\usepackage{graphicx}" in result


# ---------------------------------------------------------------------------
# File conversion
# ---------------------------------------------------------------------------

class TestFileConversion:
    def test_convert_file(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello\n\nWorld.\n", encoding="utf-8")
        out = md2tex.convert_file(str(md_file))
        assert out == str(tmp_path / "test.tex")
        tex = (tmp_path / "test.tex").read_text(encoding="utf-8")
        assert r"\section{Hello}" in tex
        assert "World." in tex

    def test_convert_file_custom_output(self, tmp_path):
        md_file = tmp_path / "input.md"
        md_file.write_text("Hello\n", encoding="utf-8")
        out_file = str(tmp_path / "output.tex")
        out = md2tex.convert_file(str(md_file), out_file)
        assert out == out_file
        assert os.path.isfile(out_file)

    def test_example_ch01(self):
        """Smoke-test the bundled Ch01.md example."""
        examples_dir = os.path.join(os.path.dirname(__file__), "..", "examples")
        ch01_md = os.path.join(examples_dir, "Ch01.md")
        if not os.path.isfile(ch01_md):
            pytest.skip("examples/Ch01.md not found")
        with open(ch01_md, encoding="utf-8") as fh:
            content = fh.read()
        result = md2tex.convert(content, standalone=True)
        assert r"\documentclass" in result
        assert r"\begin{verbatim}" in result  # block quote (verbatim) present
        assert r"\begin{table}" in result     # HTML table converted
        assert r"\begin{figure}" in result    # figure converted
        assert "$" in result                  # math preserved


# ---------------------------------------------------------------------------
# E-ink image preprocessing
# ---------------------------------------------------------------------------

def _write_minimal_png(path):
    """Write a 1x1 grayscale PNG so cache-aware path logic can see a real file."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00")

    def _chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    with open(path, "wb") as fh:
        fh.write(sig)
        fh.write(_chunk(b"IHDR", ihdr))
        fh.write(_chunk(b"IDAT", idat))
        fh.write(_chunk(b"IEND", b""))


class TestEinkPreprocessing:
    def test_no_eink_leaves_paths_alone(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        _write_minimal_png(img_dir / "fig.png")
        md = "![Alt](images/fig.png)\n"
        result = md2tex.convert(md, standalone=False, base_dir=str(tmp_path))
        assert "images/fig.png" in result
        assert "fig.eink.png" not in result

    def test_eink_rewrites_path_when_tool_runs(self, tmp_path, monkeypatch):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        src = img_dir / "fig.png"
        _write_minimal_png(src)

        def fake_run(cmd, **kwargs):
            # Materialize the destination so the cache check sees a real file.
            _write_minimal_png(cmd[-1])
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(md2tex, "_eink_tool", lambda: (["fake-tool"], "im"))
        monkeypatch.setattr(md2tex.subprocess, "run", fake_run)

        md = '![Photo](images/fig.png "Caption")\n'
        result = md2tex.convert(md, standalone=False, eink=True, base_dir=str(tmp_path))
        assert r"\includegraphics[width=\columnwidth]{images/fig.eink.png}" in result
        assert r"\caption{Caption}" in result
        assert (tmp_path / "images" / "fig.eink.png").exists()

    def test_eink_skips_unsupported_extension(self, tmp_path, monkeypatch):
        # PDFs/SVGs aren't raster — leave them alone.
        (tmp_path / "diagram.pdf").write_bytes(b"%PDF-1.4\n")
        monkeypatch.setattr(md2tex, "_eink_tool", lambda: (["fake-tool"], "im"))
        monkeypatch.setattr(
            md2tex.subprocess, "run",
            lambda *a, **kw: pytest.fail("subprocess.run should not be called"),
        )
        md = "![D](diagram.pdf)\n"
        result = md2tex.convert(md, standalone=False, eink=True, base_dir=str(tmp_path))
        assert "diagram.pdf" in result
        assert "eink" not in result

    def test_eink_falls_back_when_source_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(md2tex, "_eink_tool", lambda: (["fake-tool"], "im"))
        monkeypatch.setattr(
            md2tex.subprocess, "run",
            lambda *a, **kw: pytest.fail("subprocess.run should not be called"),
        )
        md = "![Missing](images/nope.png)\n"
        result = md2tex.convert(md, standalone=False, eink=True, base_dir=str(tmp_path))
        assert "images/nope.png" in result
        assert "eink" not in result

    def test_eink_falls_back_when_no_tool(self, tmp_path, monkeypatch):
        img = tmp_path / "fig.png"
        _write_minimal_png(img)
        monkeypatch.setattr(md2tex, "_eink_tool", lambda: None)
        md = "![X](fig.png)\n"
        result = md2tex.convert(md, standalone=False, eink=True, base_dir=str(tmp_path))
        assert "{fig.png}" in result
        assert "eink" not in result

    def test_eink_caches_when_dest_newer(self, tmp_path, monkeypatch):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        src = img_dir / "fig.png"
        dst = img_dir / "fig.eink.png"
        _write_minimal_png(src)
        _write_minimal_png(dst)
        # Ensure dst mtime >= src mtime
        src_mtime = os.path.getmtime(src)
        os.utime(dst, (src_mtime + 1, src_mtime + 1))

        calls = []
        monkeypatch.setattr(md2tex, "_eink_tool", lambda: (["fake-tool"], "im"))
        monkeypatch.setattr(
            md2tex.subprocess, "run",
            lambda *a, **kw: calls.append(a) or subprocess.CompletedProcess(a, 0),
        )

        md = "![X](images/fig.png)\n"
        result = md2tex.convert(md, standalone=False, eink=True, base_dir=str(tmp_path))
        assert "images/fig.eink.png" in result
        assert calls == []  # cache hit — no subprocess call

    def test_cli_eink_flag(self, tmp_path, monkeypatch, capsys):
        md_file = tmp_path / "doc.md"
        md_file.write_text("![X](fig.png)\n", encoding="utf-8")
        _write_minimal_png(tmp_path / "fig.png")

        def fake_run(cmd, **kwargs):
            _write_minimal_png(cmd[-1])
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(md2tex, "_eink_tool", lambda: (["fake-tool"], "im"))
        monkeypatch.setattr(md2tex.subprocess, "run", fake_run)

        rc = md2tex.main(["--eink", str(md_file)])
        assert rc == 0
        tex = (tmp_path / "doc.tex").read_text(encoding="utf-8")
        assert "fig.eink.png" in tex

    def test_cli_eink_warns_when_no_tool(self, tmp_path, monkeypatch, capsys):
        md_file = tmp_path / "doc.md"
        md_file.write_text("Hi\n", encoding="utf-8")
        monkeypatch.setattr(md2tex, "_eink_tool", lambda: None)
        rc = md2tex.main(["--eink", str(md_file)])
        assert rc == 0
        err = capsys.readouterr().err
        assert "no image tool" in err.lower()

    @pytest.mark.skipif(
        md2tex._eink_tool() is None,
        reason="no image tool (magick/convert/gm) on PATH",
    )
    def test_eink_real_tool_smoke(self, tmp_path):
        """End-to-end: actually run the local adaptive threshold pipeline."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        src = img_dir / "photo.png"
        tool, _ = md2tex._eink_tool()
        subprocess.run(
            tool + ["-size", "32x32", "xc:gray50", str(src)],
            check=True, capture_output=True,
        )

        md = "![Photo](images/photo.png)\n"
        result = md2tex.convert(md, standalone=False, eink=True, base_dir=str(tmp_path))
        assert "images/photo.eink.png" in result
        assert (img_dir / "photo.eink.png").exists()
        assert (img_dir / "photo.eink.png").stat().st_size > 0

    @pytest.mark.skipif(
        md2tex._eink_tool() is None,
        reason="no image tool (magick/convert/gm) on PATH",
    )
    def test_eink_polarity_dark_text_on_light_bg(self, tmp_path):
        """Output must keep dark ink dark and light paper light.

        Regression for the GraphicsMagick sign-convention bug: a black square
        on a white background was coming out as a black background with a
        white outline.
        """
        tool, _ = md2tex._eink_tool()
        src = tmp_path / "tile.png"
        # White canvas, black filled square in the middle.
        subprocess.run(
            tool + [
                "-size", "200x200", "xc:white",
                "-fill", "black", "-draw", "rectangle 70,70 130,130",
                str(src),
            ],
            check=True, capture_output=True,
        )

        md = "![T](tile.png)\n"
        md2tex.convert(md, standalone=False, eink=True, base_dir=str(tmp_path))

        # Inspect mean intensity of the processed output.  A 60×60 black
        # square on a 200×200 white field is ~91% white, so the mean should
        # be high.  An inverted result would be the opposite.
        out = tmp_path / "tile.eink.png"
        identify = "identify" if tool[0] == "magick" else tool[0]
        identify_cmd = [identify]
        if tool[0] == "gm":
            identify_cmd.append("identify")
        identify_cmd += ["-verbose", str(out)]
        info = subprocess.run(
            identify_cmd, check=True, capture_output=True, text=True,
        ).stdout
        # Mean line looks like "Mean: 60092.33 (0.9170)" (GM) or
        # "mean: 60092.33 (0.9170)" (IM).  Pull the parenthesised normalized
        # value — it's range-independent.
        import re as _re
        m = _re.search(r"[Mm]ean:[^\n]*\(([\d.]+)\)", info)
        assert m, f"could not parse mean from identify output:\n{info[:500]}"
        mean = float(m.group(1))
        assert mean > 0.7, f"expected mostly-white output, got mean={mean}"


