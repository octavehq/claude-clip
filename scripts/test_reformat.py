#!/usr/bin/env python3
"""
Unit tests for reformat.py.

Run from any directory:
    python3 test_reformat.py
    python3 -m unittest test_reformat.py -v

Pure stdlib. No pytest, no pip install. Tests import the sibling reformat.py.
"""

import os
import sys
import unittest

# Make sure we can import the sibling script regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reformat import (  # noqa: E402
    reformat,
    parse_blocks,
    unwrap_paragraph,
    md_inline_to_slack,
    md_inline_to_plain,
    md_inline_to_html,
)


# ---------- helpers ----------

def _dedent_raw(text: str) -> str:
    """Strip leading blank line + trailing newline from triple-quoted fixtures
    so tests read naturally."""
    if text.startswith("\n"):
        text = text[1:]
    return text


SAMPLE_WHAT_ELSE = _dedent_raw("""
⏺ What Else

  # Key insight

  The **qual-doctor** skill we built has a *hidden* duplicate of the
  [ads-resonance](https://example.com/ads) prediction card system, and
  ~~neither~~ one knows about the other yet. Use `update_entity` carefully.

  - First item that wraps across
    multiple lines
  - Second item with `inline code`
  - Third item

  0. The Move: persist test cases
  1. Unlock: regression tests
  2. Delete: the "Apply all" option

  ```python
  def foo():
      return "bar"
  ```

  > A blockquote that also
  > wraps across two lines

  ---

  Final thought about the ~~old~~ new approach.
""")


# ---------- core parse / unwrap ----------

class TestParseBlocks(unittest.TestCase):

    def test_strips_claude_bullet(self):
        blocks = parse_blocks("⏺ Hello world")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0][0], "para")
        self.assertEqual(blocks[0][1], ["Hello world"])

    def test_strips_indented_bullet(self):
        blocks = parse_blocks("    ⏺ Hello world")
        self.assertEqual(blocks[0][1], ["Hello world"])

    def test_blank_lines_split_paragraphs(self):
        blocks = parse_blocks("para one\n\npara two")
        para_blocks = [b for b in blocks if b[0] == "para"]
        self.assertEqual(len(para_blocks), 2)

    def test_separator_becomes_sep_block(self):
        blocks = parse_blocks("before\n\n---\n\nafter")
        kinds = [k for k, _ in blocks]
        self.assertEqual(kinds, ["para", "sep", "para"])

    def test_fenced_code_block(self):
        text = "```python\ndef f():\n    pass\n```"
        blocks = parse_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0][0], "code")

    def test_fenced_code_dedented_by_fence_indent(self):
        # This is Claude's 2-sp-under-⏺ case: fence opens at col 2, content
        # should come back dedented by 2.
        text = "⏺ header\n\n  ```python\n  def foo():\n      return 1\n  ```"
        blocks = parse_blocks(text)
        code_blocks = [b for b in blocks if b[0] == "code"]
        self.assertEqual(len(code_blocks), 1)
        lines = code_blocks[0][1]
        # First line is the opening fence, last is closing
        self.assertTrue(lines[0].startswith("```python"))
        self.assertTrue(lines[-1].startswith("```"))
        # Inner lines must have NO leading 2-sp indent
        self.assertEqual(lines[1], "def foo():")
        self.assertEqual(lines[2], "    return 1")  # original 4-sp indent preserved

    def test_crlf_normalized(self):
        blocks = parse_blocks("line1\r\nline2\r\n")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0][1], ["line1", "line2"])


class TestUnwrapParagraph(unittest.TestCase):

    def test_joins_softwrapped_prose(self):
        result = unwrap_paragraph(["one two", "three four", "five six"])
        self.assertEqual(result, ["one two three four five six"])

    def test_list_items_are_separate_logical_lines(self):
        result = unwrap_paragraph([
            "- First item",
            "that wraps",
            "- Second item",
        ])
        self.assertEqual(result, [
            "- First item that wraps",
            "- Second item",
        ])

    def test_blockquote_continuation_stripped(self):
        result = unwrap_paragraph([
            "> first line",
            "> second line",
            "> third line",
        ])
        self.assertEqual(result, ["> first line second line third line"])


# ---------- mode: md ----------

class TestRenderMd(unittest.TestCase):

    def test_strips_bullet_and_unwraps(self):
        out = reformat("⏺ header\n\n  first line\n  second line", "md")
        self.assertIn("header", out)
        self.assertIn("first line second line", out)
        self.assertNotIn("⏺", out)

    def test_preserves_markdown_syntax(self):
        out = reformat("⏺ text\n\n  **bold** and *italic* and `code`", "md")
        self.assertIn("**bold**", out)
        self.assertIn("*italic*", out)
        self.assertIn("`code`", out)

    def test_separator_preserved(self):
        out = reformat("before\n\n---\n\nafter", "md")
        self.assertIn("---", out)

    def test_fenced_code_dedented(self):
        out = reformat("⏺ h\n\n  ```\n  code line\n  ```", "md")
        self.assertIn("\n```\ncode line\n```\n", out)
        self.assertNotIn("  code line", out)

    def test_blockquote_unwrapped(self):
        out = reformat("> line one\n> line two", "md")
        self.assertIn("> line one line two", out)

    def test_list_items_kept(self):
        out = reformat("- a\n- b\n- c", "md")
        self.assertIn("- a", out)
        self.assertIn("- b", out)
        self.assertIn("- c", out)


# ---------- mode: slack ----------

class TestRenderSlack(unittest.TestCase):

    def test_bold_markdown_becomes_slack_bold(self):
        out = md_inline_to_slack("**bold**")
        self.assertEqual(out, "*bold*")

    def test_italic_star_becomes_underscore(self):
        out = md_inline_to_slack("*italic*")
        self.assertEqual(out, "_italic_")

    def test_bold_and_italic_coexist(self):
        # Regression: bold must not be re-matched as italic
        out = md_inline_to_slack("**bold** and *italic*")
        self.assertEqual(out, "*bold* and _italic_")

    def test_link_preserved_as_markdown(self):
        out = md_inline_to_slack("[label](https://example.com)")
        self.assertEqual(out, "[label](https://example.com)")

    def test_strikethrough(self):
        out = md_inline_to_slack("~~gone~~")
        self.assertEqual(out, "~gone~")

    def test_header_becomes_bold_line(self):
        out = reformat("# Title\n\nbody", "slack")
        self.assertIn("*Title*", out)
        self.assertNotIn("#", out)

    def test_code_fence_strips_language_hint(self):
        out = reformat("```python\nx = 1\n```", "slack")
        # Opening fence should be bare ```
        self.assertIn("```\nx = 1\n```", out)

    def test_list_items_preserved(self):
        out = reformat("- a\n- b", "slack")
        self.assertIn("- a", out)
        self.assertIn("- b", out)

    def test_asterisk_list_marker_not_confused_with_bold(self):
        # Not a common case (lists use -), but guard against it
        out = md_inline_to_slack("not *starred* text")
        self.assertEqual(out, "not _starred_ text")


# ---------- mode: plain ----------

class TestRenderPlain(unittest.TestCase):

    def test_bold_stripped(self):
        self.assertEqual(md_inline_to_plain("**bold**"), "bold")

    def test_italic_stripped(self):
        self.assertEqual(md_inline_to_plain("*italic*"), "italic")
        self.assertEqual(md_inline_to_plain("_italic_"), "italic")

    def test_inline_code_stripped(self):
        self.assertEqual(md_inline_to_plain("`code`"), "code")

    def test_strikethrough_stripped(self):
        self.assertEqual(md_inline_to_plain("~~gone~~"), "gone")

    def test_link_flattened(self):
        self.assertEqual(
            md_inline_to_plain("[label](https://example.com)"),
            "label (https://example.com)",
        )

    def test_header_becomes_plain_line(self):
        out = reformat("# Title", "plain")
        self.assertIn("Title", out)
        self.assertNotIn("#", out)

    def test_fenced_code_content_preserved_no_fence(self):
        out = reformat("```\nhello\n```", "plain")
        self.assertIn("hello", out)
        self.assertNotIn("```", out)


# ---------- mode: html ----------

class TestRenderHtml(unittest.TestCase):

    def test_paragraph_wraps_in_p(self):
        out = reformat("hello world", "html")
        self.assertIn("<p>hello world</p>", out)

    def test_header_level(self):
        out = reformat("# H1\n\n## H2\n\n### H3", "html")
        self.assertIn("<h1>H1</h1>", out)
        self.assertIn("<h2>H2</h2>", out)
        self.assertIn("<h3>H3</h3>", out)

    def test_bold_and_italic(self):
        out = md_inline_to_html("**bold** and *italic*")
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn("<em>italic</em>", out)

    def test_inline_code_escaped(self):
        out = md_inline_to_html("`a < b`")
        self.assertIn("<code>a &lt; b</code>", out)

    def test_link(self):
        out = md_inline_to_html("[label](https://example.com)")
        self.assertIn('<a href="https://example.com">label</a>', out)

    def test_unordered_list(self):
        out = reformat("- a\n- b\n- c", "html")
        self.assertIn("<ul>", out)
        self.assertIn("<li>a</li>", out)
        self.assertIn("<li>c</li>", out)
        self.assertIn("</ul>", out)

    def test_ordered_list(self):
        out = reformat("1. a\n2. b", "html")
        self.assertIn("<ol>", out)
        self.assertIn("<li>a</li>", out)

    def test_code_block_with_language(self):
        out = reformat("```python\nx = 1\n```", "html")
        self.assertIn('<pre><code class="language-python">', out)
        self.assertIn("x = 1", out)

    def test_code_block_escapes_html(self):
        out = reformat("```\n<script>alert(1)</script>\n```", "html")
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script>", out)

    def test_blockquote(self):
        out = reformat("> a quote", "html")
        self.assertIn("<blockquote>", out)
        self.assertIn("a quote", out)

    def test_horizontal_rule(self):
        out = reformat("before\n\n---\n\nafter", "html")
        self.assertIn("<hr>", out)

    def test_html_special_chars_escaped_in_prose(self):
        out = reformat("5 < 10 & 10 > 5", "html")
        self.assertIn("&lt;", out)
        self.assertIn("&gt;", out)
        self.assertIn("&amp;", out)


# ---------- end-to-end: the WhatElse sample ----------

class TestWhatElseSample(unittest.TestCase):
    """End-to-end smoke tests against a realistic Claude Code output."""

    def test_md_removes_bullet_and_indent(self):
        out = reformat(SAMPLE_WHAT_ELSE, "md")
        self.assertNotIn("⏺", out)
        self.assertNotIn("  First item", out)  # 2-sp indent gone
        self.assertIn("What Else", out)
        self.assertIn("- First item that wraps across multiple lines", out)
        self.assertIn("```python", out)
        self.assertIn("> A blockquote that also wraps across two lines", out)

    def test_md_unwraps_paragraph(self):
        out = reformat(SAMPLE_WHAT_ELSE, "md")
        # The three-line sentence must join into one line
        self.assertIn(
            "The **qual-doctor** skill we built has a *hidden* duplicate of the "
            "[ads-resonance](https://example.com/ads) prediction card system, and "
            "~~neither~~ one knows about the other yet. Use `update_entity` carefully.",
            out,
        )

    def test_slack_converts_inline(self):
        out = reformat(SAMPLE_WHAT_ELSE, "slack")
        self.assertIn("*qual-doctor*", out)           # bold
        self.assertIn("_hidden_", out)                # italic
        self.assertIn("[ads-resonance](https://example.com/ads)", out)  # link preserved as MD
        self.assertIn("~neither~", out)               # strikethrough (single tilde)
        self.assertNotIn("~~neither~~", out)          # not the double
        self.assertIn("*Key insight*", out)           # header as bold

    def test_plain_strips_all_markdown(self):
        out = reformat(SAMPLE_WHAT_ELSE, "plain")
        self.assertNotIn("**", out)
        self.assertNotIn("~~", out)
        self.assertNotIn("```", out)
        self.assertNotIn("#", out)
        self.assertIn("qual-doctor", out)
        self.assertIn("ads-resonance (https://example.com/ads)", out)
        self.assertIn("def foo():", out)  # code content preserved

    def test_html_produces_valid_structure(self):
        out = reformat(SAMPLE_WHAT_ELSE, "html")
        self.assertIn("<h1>Key insight</h1>", out)
        self.assertIn("<strong>qual-doctor</strong>", out)
        self.assertIn("<em>hidden</em>", out)
        self.assertIn('<a href="https://example.com/ads">ads-resonance</a>', out)
        self.assertIn("<del>neither</del>", out)
        self.assertIn("<ul>", out)
        self.assertIn("<ol>", out)
        self.assertIn('<pre><code class="language-python">', out)
        self.assertIn("<blockquote>", out)
        self.assertIn("<hr>", out)


# ---------- edge cases ----------

class TestEdgeCases(unittest.TestCase):

    def test_empty_input(self):
        self.assertEqual(reformat("", "md").strip(), "")
        self.assertEqual(reformat("", "slack").strip(), "")
        self.assertEqual(reformat("", "plain").strip(), "")
        self.assertEqual(reformat("", "html").strip(), "")

    def test_only_whitespace(self):
        out = reformat("   \n\n  \n", "md")
        self.assertEqual(out.strip(), "")

    def test_only_bullet_marker(self):
        out = reformat("⏺", "md")
        self.assertEqual(out.strip(), "")

    def test_dollar_sign_literal_in_slack(self):
        # Regression guard: shell $VAR shouldn't matter because the skill uses
        # a quoted heredoc, but the reformatter itself must not mangle it either.
        out = reformat("Use $HOME/bin", "md")
        self.assertIn("$HOME/bin", out)

    def test_backticks_with_dollar(self):
        out = reformat("run `echo $PATH` now", "md")
        self.assertIn("`echo $PATH`", out)

    def test_unterminated_code_fence_doesnt_crash(self):
        # Missing closing ``` — should still produce output, not raise
        out = reformat("```python\nx = 1\n", "md")
        self.assertIsInstance(out, str)

    def test_inline_code_with_html_chars(self):
        out = reformat("use `<div>` element", "html")
        # The < and > inside inline code should be escaped
        self.assertIn("<code>&lt;div&gt;</code>", out)

    def test_asterisk_in_list_item_not_broken(self):
        # A list with bold inside an item
        out = reformat("- item with **bold** text\n- plain item", "slack")
        self.assertIn("*bold*", out)  # bold preserved as Slack bold
        self.assertIn("- item with *bold* text", out)

    def test_link_inside_bold(self):
        out = md_inline_to_slack("**see [here](https://x.com)**")
        # Bold should be *, link preserved as Markdown
        self.assertIn("[here](https://x.com)", out)
        self.assertIn("*", out)

    def test_trailing_newlines_collapsed(self):
        out = reformat("hello\n\n\n\n\n", "md")
        # Should not produce runs of blank lines
        self.assertFalse("\n\n\n" in out)

    def test_no_bullet_at_all(self):
        # Input without ⏺ should still get dedented + unwrapped
        out = reformat("  first line\n  second line", "md")
        self.assertIn("first line second line", out)


# ---------- comprehensive Slack test ----------

COMPREHENSIVE_SLACK_TEST = _dedent_raw("""
# Slack Format Test

Here's a **comprehensive test** of all _Markdown formatting_ that Slack supports.

## Headers become bold lines

### Third-level header too

Regular paragraph with **bold text**, *italic text*, and ~~strikethrough text~~ inline. Also `inline code` stays as-is.

> This is a blockquote that should render nicely in Slack.

- Unordered list item one
- Unordered list item two
- Unordered list item three

1. Ordered list item one
2. Ordered list item two
3. Ordered list item three

Here's a [link to Octave](https://octavehq.com) and a [link to Google](https://google.com) inline.

Mixed paragraph with **bold and *nested italic*** plus a [link](https://example.com) and some `code` and ~~struck text~~ all together.

| Feature | Status | Owner |
|---------|--------|-------|
| Bold/italic | Done | Julian |
| Tables | Testing | Claude |
| Links | Done | Julian |

```python
def hello():
    print("fenced code block preserved")
```

---

Final line after a separator.
""")


class TestComprehensiveSlack(unittest.TestCase):
    """End-to-end test using the comprehensive Slack test message."""

    def test_slack_headers_become_bold(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertIn("*Slack Format Test*", out)
        self.assertIn("*Headers become bold lines*", out)
        self.assertIn("*Third-level header too*", out)
        self.assertNotIn("# ", out)
        self.assertNotIn("## ", out)
        self.assertNotIn("### ", out)

    def test_slack_bold_italic_strikethrough(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertIn("*bold text*", out)
        self.assertIn("_italic text_", out)
        self.assertIn("~strikethrough text~", out)
        self.assertNotIn("**bold text**", out)
        self.assertNotIn("~~strikethrough text~~", out)

    def test_slack_nested_bold_italic(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        # Bold wraps the whole phrase, italic is nested inside
        self.assertIn("*bold and _nested italic*_", out)

    def test_slack_inline_code_preserved(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertIn("`inline code`", out)
        self.assertIn("`code`", out)

    def test_slack_blockquote(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertIn("> This is a blockquote", out)

    def test_slack_unordered_list(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertIn("- Unordered list item one", out)
        self.assertIn("- Unordered list item two", out)
        self.assertIn("- Unordered list item three", out)

    def test_slack_ordered_list(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertIn("1. Ordered list item one", out)
        self.assertIn("2. Ordered list item two", out)
        self.assertIn("3. Ordered list item three", out)

    def test_slack_links_preserved_as_markdown(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertIn("[link to Octave](https://octavehq.com)", out)
        self.assertIn("[link to Google](https://google.com)", out)

    def test_slack_table_becomes_code_block(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertIn("```\n", out)
        self.assertIn("Feature", out)
        self.assertIn("Bold/italic", out)
        self.assertIn("Testing", out)
        # Separator row (|---|---|) should NOT appear
        self.assertNotIn("|------", out)

    def test_slack_table_columns_aligned(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        # Extract the code block containing the table
        in_code = False
        table_lines = []
        for line in out.split("\n"):
            if line.strip() == "```" and not in_code:
                in_code = True
                continue
            if line.strip() == "```" and in_code:
                break
            if in_code:
                table_lines.append(line)
        # All data lines should be the same length (padded)
        if table_lines:
            lengths = [len(l.rstrip()) for l in table_lines if l.strip()]
            self.assertTrue(
                len(set(lengths)) <= 2,  # header + separator may differ slightly
                f"Table columns not aligned: line lengths = {lengths}"
            )

    def test_slack_code_fence_strips_language(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertNotIn("```python", out)
        self.assertIn("def hello():", out)

    def test_slack_separator(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertIn("────────", out)

    def test_slack_final_line(self):
        out = reformat(COMPREHENSIVE_SLACK_TEST, "slack")
        self.assertIn("Final line after a separator.", out)


# ---------- table-specific tests ----------

class TestTableHandling(unittest.TestCase):

    def test_md_preserves_table_rows(self):
        table = "| A | B |\n|---|---|\n| 1 | 2 |"
        out = reformat(table, "md")
        self.assertIn("| A | B |", out)
        self.assertIn("|---|---|", out)
        self.assertIn("| 1 | 2 |", out)

    def test_slack_table_is_code_block(self):
        table = "| Name | Score |\n|------|-------|\n| Alice | 95 |\n| Bob | 87 |"
        out = reformat(table, "slack")
        self.assertIn("```\n", out)
        self.assertIn("Alice", out)
        self.assertIn("Bob", out)
        self.assertNotIn("|", out.replace("```", ""))  # no pipe chars outside fence

    def test_slack_table_separator_row_filtered(self):
        table = "| H1 | H2 |\n|-----|-----|\n| a | b |"
        out = reformat(table, "slack")
        self.assertNotIn("|--", out)

    def test_slack_table_has_header_separator(self):
        table = "| H1 | H2 |\n|-----|-----|\n| a | b |"
        out = reformat(table, "slack")
        # Should have a dash-based separator after header
        lines = [l for l in out.split("\n") if l.strip() and l.strip() != "```"]
        self.assertTrue(any(set(l.strip()) <= {"-", " "} for l in lines),
                        "Expected a dash separator line after header")

    def test_plain_table_preserved(self):
        table = "| A | B |\n|---|---|\n| 1 | 2 |"
        out = reformat(table, "plain")
        self.assertIn("A", out)
        self.assertIn("1", out)

    def test_html_table_structure(self):
        table = "| A | B |\n|---|---|\n| 1 | 2 |"
        out = reformat(table, "html")
        self.assertIn("<table>", out)
        self.assertIn("</table>", out)
        self.assertIn("<thead>", out)
        self.assertIn("<tbody>", out)
        self.assertIn("<th>A</th>", out)
        self.assertIn("<th>B</th>", out)
        self.assertIn("<td>1</td>", out)
        self.assertIn("<td>2</td>", out)

    def test_html_table_separator_filtered(self):
        table = "| H1 | H2 |\n|-----|-----|\n| a | b |"
        out = reformat(table, "html")
        self.assertNotIn("---", out)

    def test_html_table_with_inline_formatting(self):
        table = "| Name | Status |\n|------|--------|\n| **Alice** | *active* |"
        out = reformat(table, "html")
        self.assertIn("<strong>Alice</strong>", out)
        self.assertIn("<em>active</em>", out)

    def test_html_table_multi_row(self):
        table = "| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n| 7 | 8 | 9 |"
        out = reformat(table, "html")
        # 1 header row, 3 body rows
        self.assertEqual(out.count("<th>"), 3)
        self.assertEqual(out.count("<td>"), 9)

    def test_html_table_mixed_with_prose(self):
        text = "Before.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nAfter."
        out = reformat(text, "html")
        self.assertIn("<p>Before.</p>", out)
        self.assertIn("<table>", out)
        self.assertIn("<p>After.</p>", out)

    def test_table_mixed_with_prose(self):
        text = "Here's a table:\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nAnd more text."
        out = reformat(text, "slack")
        self.assertIn("Here's a table:", out)
        self.assertIn("And more text.", out)
        self.assertIn("```\n", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
