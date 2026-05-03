"""Tests for md2tex.py — Markdown to LaTeX converter."""

import os
import sys
import textwrap

import pytest

# Add the repository root to the path so we can import md2tex.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
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
        assert r"\begin{quote}" in result
        assert "This is a block quote." in result
        assert r"\end{quote}" in result

    def test_tab_indented_multi_line(self):
        md = "\tFirst line.\n\tSecond line.\n"
        result = body(md)
        assert result.count(r"\begin{quote}") == 1
        assert result.count(r"\end{quote}") == 1
        assert "First line." in result
        assert "Second line." in result

    def test_four_space_indented(self):
        md = "    Indented with four spaces.\n"
        result = body(md)
        assert r"\begin{quote}" in result
        assert "Indented with four spaces." in result
        assert r"\end{quote}" in result

    def test_standard_prefix(self):
        md = "> A quoted line.\n"
        result = body(md)
        assert r"\begin{quote}" in result
        assert "A quoted line." in result
        assert r"\end{quote}" in result

    def test_standard_prefix_multi_line(self):
        md = "> Line one.\n> Line two.\n"
        result = body(md)
        assert result.count(r"\begin{quote}") == 1
        assert result.count(r"\end{quote}") == 1

    def test_quote_closed_before_heading(self):
        md = "> Quote text.\n\n# Heading\n"
        result = body(md)
        # The quote must be closed before the heading command.
        quote_end = result.index(r"\end{quote}")
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
        assert r"\includegraphics{images/fig01.png}" in result
        assert r"\caption{My Caption}" in result
        assert r"\label{fig:fig01}" in result
        assert r"\end{figure}" in result

    def test_figure_without_caption_uses_alt(self):
        md = "![Diagram](images/diagram.png)\n"
        result = body(md)
        assert r"\includegraphics{images/diagram.png}" in result
        assert r"\caption{Diagram}" in result
        assert r"\label{fig:diagram}" in result

    def test_figure_subdirectory_path(self):
        md = "![Graph](figures/chapter1/graph.pdf)\n"
        result = body(md)
        assert r"\includegraphics{figures/chapter1/graph.pdf}" in result
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
        assert r"\begin{quote}" in result     # block quote present
        assert r"\begin{table}" in result     # HTML table converted
        assert r"\begin{figure}" in result    # figure converted
        assert "$" in result                  # math preserved
