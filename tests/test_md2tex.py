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

    def test_currency_single_dollar_escaped(self):
        md = "A final payment of $90.\n"
        result = body(md)
        assert r"\$90" in result
        assert "$90" not in result.replace(r"\$90", "")

    def test_currency_multiple_dollars_in_paragraph_escaped(self):
        md = "He earned $12 to $18 a month and saved $300.\n"
        result = body(md)
        assert r"\$12" in result
        assert r"\$18" in result
        assert r"\$300" in result

    def test_currency_does_not_break_real_inline_math(self):
        md = "The price is $50 but the formula is $x^2 + y^2 = z^2$.\n"
        result = body(md)
        assert r"\$50" in result
        assert "$x^2 + y^2 = z^2$" in result

    def test_already_escaped_dollar_left_alone(self):
        md = "He paid \\$90 for it.\n"
        result = body(md)
        assert result.count(r"\$90") == 1
        assert r"\\$90" not in result


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

class TestFigures:
    def test_figure_with_caption(self):
        md = '![Alt text](images/fig01.png "My Caption")\n'
        result = body(md)
        assert r"\begin{figure}" in result
        assert r"\centering" in result
        # Source file doesn't exist → unknown aspect ratio falls back to 0.5.
        assert r"\includegraphics[width=0.5\columnwidth]{images/fig01.png}" in result
        assert r"\caption{My Caption}" in result
        assert r"\label{fig:fig01}" in result
        assert r"\end{figure}" in result

    def test_figure_without_caption_uses_alt(self):
        md = "![Diagram](images/diagram.png)\n"
        result = body(md)
        assert r"\includegraphics[width=0.5\columnwidth]{images/diagram.png}" in result
        assert r"\caption{Diagram}" in result
        assert r"\label{fig:diagram}" in result

    def test_figure_subdirectory_path(self):
        md = "![Graph](figures/chapter1/graph.pdf)\n"
        result = body(md)
        assert r"\includegraphics[width=0.5\columnwidth]{figures/chapter1/graph.pdf}" in result
        assert r"\label{fig:graph}" in result

    def test_figure_environment_tags(self):
        md = '![X](imgs/x.png "Caption X")\n'
        result = body(md)
        assert r"\begin{figure}[htbp]" in result
        assert r"\end{figure}" in result

    def test_landscape_image_uses_wide_width(self, tmp_path):
        # Width > height → 0.7\columnwidth.
        _write_sized_png(tmp_path / "wide.png", 200, 100)
        result = md2tex.convert(
            "![W](wide.png)\n", standalone=False, base_dir=str(tmp_path)
        )
        assert r"\includegraphics[width=0.7\columnwidth]{wide.png}" in result

    def test_portrait_image_uses_narrow_width(self, tmp_path):
        # Height > width → 0.5\columnwidth.
        _write_sized_png(tmp_path / "tall.png", 100, 200)
        result = md2tex.convert(
            "![T](tall.png)\n", standalone=False, base_dir=str(tmp_path)
        )
        assert r"\includegraphics[width=0.5\columnwidth]{tall.png}" in result

    def test_square_image_uses_narrow_width(self, tmp_path):
        # w == h → "otherwise" branch → 0.5.
        _write_sized_png(tmp_path / "sq.png", 120, 120)
        result = md2tex.convert(
            "![S](sq.png)\n", standalone=False, base_dir=str(tmp_path)
        )
        assert r"\includegraphics[width=0.5\columnwidth]{sq.png}" in result


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


class TestAllCapsHeadings:
    def test_single_all_caps_line_becomes_subsection_star(self):
        assert r"\subsection*{Delaware Valley}" in body("DELAWARE VALLEY\n")

    def test_consecutive_all_caps_lines_joined(self):
        md = "GROWING DIVERSITY ON THE DELAWARE:\nFRIENDS, FRIENDLIES, AND OTHERS\n"
        expected = (
            r"\subsection*{Growing Diversity On The Delaware: "
            r"Friends, Friendlies, And Others}"
        )
        assert expected in body(md)

    def test_all_caps_with_apostrophe(self):
        assert r"\subsection*{The Friends' Migration}" in body("THE FRIENDS' MIGRATION\n")

    def test_mixed_case_line_not_promoted(self):
        result = body("Quaker Founders, Guinea Achievers, American Reformers\n")
        assert r"\subsection" not in result

    def test_blank_separated_caps_runs_not_joined(self):
        md = "FIRST HEADING\n\nSECOND HEADING\n"
        result = body(md)
        assert r"\subsection*{First Heading}" in result
        assert r"\subsection*{Second Heading}" in result
        assert "First Heading Second Heading" not in result

    def test_single_letter_not_promoted(self):
        result = body("I\n")
        assert r"\subsection" not in result

    def test_all_caps_inside_blockquote_not_promoted(self):
        result = body("> SHOUTED WORDS\n")
        assert r"\subsection" not in result
        assert r"\begin{verbatim}" in result

    def test_all_caps_inside_code_block_not_promoted(self):
        result = body("```\nSHOUTED CODE\n```\n")
        assert r"\subsection" not in result
        assert "SHOUTED CODE" in result

    def test_all_caps_heading_closes_open_list(self):
        md = "- item one\n- item two\nALL CAPS HEADING\n"
        result = body(md)
        list_end = result.index(r"\end{itemize}")
        heading_start = result.index(r"\subsection*")
        assert list_end < heading_start

    def test_markdown_heading_takes_precedence_over_all_caps(self):
        result = body("# REAL HEADING\n")
        assert r"\section{REAL HEADING}" in result
        assert r"\subsection*" not in result


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

    def test_endash_in_prose_normalized(self):
        # Prose normalization collapses Unicode dashes to LaTeX-canonical form.
        md = "Years 1716–1807 spanned a century.\n"
        result = body(md)
        assert "1716--1807" in result
        assert "–" not in result

    def test_superscript_in_blockquote_replaced(self):
        md = "> Akan Ethics, 1988²\n"
        result = body(md)
        assert "1988^2" in result
        assert "²" not in result

    def test_multidigit_superscript_in_blockquote_replaced(self):
        # Verbatim has no math mode, so each char is mapped independently
        # (`^1^2`) rather than grouped into `^{12}`.
        md = "> See note¹²\n"
        result = body(md)
        assert "note^1^2" in result
        assert "¹" not in result and "²" not in result


# ---------------------------------------------------------------------------
# Unicode superscript footnote markers
# ---------------------------------------------------------------------------

class TestSuperscriptConversion:
    def test_single_digit_superscript(self):
        result = body("Akan Ethics, 1988²\n")
        assert "1988$^2$" in result
        assert "²" not in result

    def test_trailing_superscript_after_punctuation(self):
        result = body("Rhode Island.⁴\n")
        assert "Island.$^4$" in result

    def test_multidigit_superscript_uses_braces(self):
        result = body("See note¹²\n")
        assert "note$^{12}$" in result

    def test_superscript_zero_through_nine(self):
        # All Unicode superscript digits should map.
        result = body("a⁰b¹c²d³e⁴f⁵g⁶h⁷i⁸j⁹\n")
        for d in "0123456789":
            assert f"$^{d}$" in result

    def test_superscript_inside_math_preserved(self):
        # Inside $...$ the original char should not be touched.
        result = body("Inline $x²$ end.\n")
        assert "$x²$" in result

    def test_superscript_plus_minus(self):
        result = body("ion X⁺ and Y⁻\n")
        assert "X$^+$" in result
        assert "Y$^-$" in result


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
# Hyphen / dash normalization
# ---------------------------------------------------------------------------

class TestHyphenNormalization:
    def test_endash_to_double_hyphen(self):
        result = body("pages 12–34\n")
        assert "pages 12--34" in result
        assert "–" not in result

    def test_emdash_to_triple_hyphen(self):
        result = body("Wait — really?\n")
        assert "Wait --- really?" in result
        assert "—" not in result

    def test_hyphen_char_to_ascii(self):
        result = body("co‐operate\n")
        assert "co-operate" in result
        assert "‐" not in result

    def test_nonbreaking_hyphen_to_ascii(self):
        result = body("X‑Y\n")
        assert "X-Y" in result
        assert "‑" not in result

    def test_figure_dash_to_double_hyphen(self):
        result = body("555‒1212\n")
        assert "555--1212" in result

    def test_horizontal_bar_to_triple_hyphen(self):
        result = body("quote― attribution\n")
        assert "quote--- attribution" in result

    def test_minus_sign_to_ascii(self):
        result = body("temp −5 degrees\n")
        assert "temp -5 degrees" in result

    def test_soft_hyphen_dropped(self):
        result = body("super­califragilistic\n")
        assert "supercalifragilistic" in result
        assert "­" not in result

    def test_ascii_hyphen_unchanged(self):
        result = body("well-known fact\n")
        assert "well-known fact" in result

    def test_dashes_in_math_preserved(self):
        # Inside $...$ Unicode dashes/minus shouldn't be touched.
        result = body("Equation $a − b = c – d$ end.\n")
        assert "$a − b = c – d$" in result

    def test_endash_in_html_table_cell_normalized(self):
        # Cells go through their own pipeline; hyphen normalization must run
        # there too, otherwise raw en-dashes leak into the emitted .tex.
        md = "<table>\n<tr><td>1733–34</td><td>449</td></tr>\n</table>\n"
        result = body(md)
        assert "1733--34" in result
        assert "–" not in result

    def test_endash_in_html_table_header_normalized(self):
        md = "<table>\n<tr><th>1716–44</th></tr>\n</table>\n"
        result = body(md)
        assert r"\textbf{1716--44}" in result
        assert "–" not in result


# ---------------------------------------------------------------------------
# Ampersand escaping
# ---------------------------------------------------------------------------

class TestAmpersandEscaping:
    def test_plain_ampersand_in_paragraph(self):
        # Mixed-case prose so the ALL-CAPS heading detector doesn't fire
        # and re-case the line out from under us.
        assert r"Reading AT\&T docs" in body("Reading AT&T docs\n")

    def test_already_escaped_ampersand_unchanged(self):
        # Existing \& should not become \\&.
        result = body(r"Reading AT\&T docs" + "\n")
        assert r"Reading AT\&T docs" in result
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
# Percent escaping
# ---------------------------------------------------------------------------

class TestPercentEscaping:
    def test_plain_percent_in_paragraph(self):
        assert r"50\%" in body("50% off today.\n")

    def test_already_escaped_percent_unchanged(self):
        result = body(r"50\% off" + "\n")
        assert r"50\% off" in result
        assert r"\\%" not in result

    def test_multiple_percents(self):
        result = body("Up 10% then down 5% then 0%.\n")
        assert r"10\%" in result
        assert r"5\%" in result
        assert r"0\%" in result

    def test_percent_in_inline_math_preserved(self):
        # Inside math, % is still a comment to LaTeX, but the user's source is
        # what it is — don't molest math regions.
        result = body(r"Inline $a \% b$ here." + "\n")
        assert r"$a \% b$" in result

    def test_percent_outside_math_escaped_when_math_present(self):
        result = body("Win rate 60% with $a + b$ end.\n")
        assert r"60\%" in result
        assert "$a + b$" in result

    def test_percent_in_url_escaped(self):
        result = body("[link](https://x.test/a%20b)\n")
        assert r"\href{https://x.test/a\%20b}{link}" in result

    def test_html_table_cell_percent_escaped(self):
        md = (
            "<table>\n"
            "<tr><td>301 (0.7%)</td><td>196 (0.6%)</td></tr>\n"
            "</table>\n"
        )
        result = body(md)
        assert r"301 (0.7\%)" in result
        assert r"196 (0.6\%)" in result
        # Sanity: no bare `%)` survives in a table cell.
        assert "0.7%)" not in result
        assert "0.6%)" not in result


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
# Index post-processing
# ---------------------------------------------------------------------------

class TestIndexPostProcessing:
    def test_entries_become_separate_paragraphs(self):
        # Two consecutive entries in the source markdown collapse into one
        # flowing paragraph without post-processing.  After the pass, each
        # entry sits on its own \par.
        md = "INDEX\n\nAaron, 653, 656\nabolition, see antislavery\n"
        result = body(md)
        assert r"\noindent Aaron, 653, 656\par" in result
        assert r"\noindent abolition, see antislavery\par" in result

    def test_hangindent_used_for_continuation(self):
        md = "INDEX\n\nAaron, 653, 656\n"
        result = body(md)
        assert r"\hangindent=1em" in result
        assert r"\hangafter=1" in result

    def test_explainer_paragraph_kept_as_prose(self):
        # The leading explainer ("Page numbers in italics ...") has no page
        # refs and shouldn't be wrapped as an entry.
        md = (
            "INDEX\n\n"
            "Page numbers in italics refer to illustrations and tables.\n\n"
            "Aaron, 653, 656\n"
        )
        result = body(md)
        # The explainer line stays as plain prose.
        assert "Page numbers in italics refer to illustrations and tables." in result
        # The explainer is NOT wrapped in a hangindent paragraph.
        assert (
            r"\hangindent=1em\hangafter=1\noindent Page numbers" not in result
        )
        # The actual entry is.
        assert r"\noindent Aaron, 653, 656\par" in result

    def test_colon_terminated_entry_recognised(self):
        # A main entry like "African Americans:" has no page refs but must
        # still be split off so it doesn't merge into the next entry.
        md = "INDEX\n\nAfrican Americans:\nin American Revolution, 78\n"
        result = body(md)
        assert r"\noindent African Americans:\par" in result
        assert r"\noindent in American Revolution, 78\par" in result

    def test_no_index_section_leaves_body_untouched(self):
        # Without an "Index" heading the post-processor should be a no-op.
        md = "Aaron, 653, 656\nabolition, 178--80\n"
        result = body(md)
        assert r"\hangindent" not in result
        assert r"\begingroup" not in result

    def test_section_after_index_closes_group(self):
        # A new section heading after the index should end index mode and
        # close the begingroup so subsequent content typesets normally.
        md = (
            "INDEX\n\n"
            "Aaron, 653, 656\n"
            "\n"
            "# Next Chapter\n\n"
            "Body text here.\n"
        )
        result = body(md)
        # The endgroup must appear before the next \section.
        endgroup_idx = result.index(r"\endgroup")
        section_idx = result.index(r"\section{Next Chapter}")
        assert endgroup_idx < section_idx

    def test_indented_lines_render_as_subentries(self):
        # An indented line under the INDEX heading should render as a sub-
        # entry (deeper hangindent + leading hspace), and crucially must
        # NOT trigger the block-quote rule that would put it in verbatim.
        md = (
            "INDEX\n\n"
            "Creek nation, 396, 685\n"
            "    Black Seminoles as slaves of, 708\n"
            "    in War of 1812, 697\n"
        )
        result = body(md)
        assert r"\noindent Creek nation, 396, 685\par" in result
        assert r"\hangindent=2em" in result
        assert r"\hspace*{1em}Black Seminoles as slaves of, 708\par" in result
        assert r"\hspace*{1em}in War of 1812, 697\par" in result
        # The pre-pass should have prevented the verbatim block from firing.
        assert r"\begin{verbatim}" not in result
        # The internal sub-entry token must not leak into output.
        assert "idxsub" not in result

    def test_subentry_token_does_not_leak_outside_index(self):
        # If somehow a marked line ends up outside an index section (e.g.
        # the section heading isn't recognised), the defensive strip in
        # convert() should remove the marker so it never reaches the PDF.
        md = (
            "Some prose paragraph.\n"
            "    Indented line under non-index prose.\n"
        )
        result = body(md)
        assert "idxsub" not in result

    def test_entry_with_quoted_phrase_before_pages(self):
        # "as skilled "horse gentlers," 614--21" — the comma sits before
        # a closing quote, not directly before the page digits.  The
        # detector must still recognise this as an entry.
        md = "INDEX\n\nas skilled \"horse gentlers,\" 614--21\n"
        result = body(md)
        assert r"\hangindent=1em\hangafter=1\noindent" in result
        # The line must be wrapped, not left as bare paragraph text.
        assert r"\par" in result.split(r"\hangindent=1em\hangafter=1\noindent ")[1]

    def test_pageref_only_after_quote_is_entry(self):
        # "Adams, John Quincy, 692." (period after page number) should
        # qualify even though it ends with a punctuation char.
        md = "INDEX\n\nAdams, John Quincy, 692.\n"
        result = body(md)
        assert r"\noindent Adams, John Quincy, 692.\par" in result


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

def _write_sized_png(path, width: int, height: int):
    """Write a grayscale PNG with a valid IHDR for dimension-based assertions.

    The IDAT payload doesn't actually decode to a *width × height* image —
    that's fine: nothing in the test suite decodes pixels, and the
    dimension parser only reads IHDR.
    """
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
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


def _write_minimal_png(path):
    """Write a 1x1 grayscale PNG so cache-aware path logic can see a real file."""
    _write_sized_png(path, 1, 1)


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
        # Test PNG is 1×1 (square), so the width factor is the non-landscape default.
        assert r"\includegraphics[width=0.5\columnwidth]{images/fig.eink.png}" in result
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
        """End-to-end: actually run the grayscale-with-contrast pipeline."""
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

        Sanity check that the pipeline never inverts tones — historically
        a GraphicsMagick option-syntax mismatch could flip a black square
        on white into the opposite, and the same risk exists for any future
        argument tweak.
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


