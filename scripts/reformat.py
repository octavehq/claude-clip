#!/usr/bin/env python3
"""
Reformat Claude Code output for clean pasting, with optional format conversion.

Pipeline:
    1. Normalize line endings
    2. Strip leading ⏺ bullet markers
    3. Parse into blocks (paragraphs, lists, fenced code, separators)
    4. Unwrap soft-wrapped paragraph lines
    5. Apply mode-specific rewrite (keep as Markdown, Slack mrkdwn, plain, HTML)

Modes:
    md (default)  Strip ⏺/indent, unwrap paragraphs, keep Markdown as-is
    slack         + Convert Markdown → Slack mrkdwn (bold, links, headers, strike)
    plain         + Strip Markdown syntax, keep plain text
    html          + Convert Markdown → HTML (paragraphs, lists, headers, inline)

Usage:
    reformat.py                          # clipboard → clipboard, mode=md
    reformat.py -m slack                 # clipboard → clipboard, mode=slack
    reformat.py -m html --stdout         # clipboard → stdout, mode=html
    reformat.py -m plain -               # stdin → stdout, mode=plain
    pbpaste | reformat.py -m slack -     # stdin → stdout via pipe

Pure stdlib. Clipboard mode is macOS-only (pbcopy/pbpaste); stdin/stdout
modes work anywhere Python 3 runs.
"""

import argparse
import html as htmllib
import re
import subprocess
import sys
from typing import List, Tuple


# ---------- clipboard helpers (macOS) ----------

def get_clipboard() -> str:
    return subprocess.check_output(["pbpaste"]).decode("utf-8")


def set_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


# ---------- core parse & unwrap ----------

Block = Tuple[str, List[str]]  # kind in {"para", "code", "sep"}


def parse_blocks(text: str) -> List[Block]:
    """Split raw text into typed blocks. Paragraph lines remain hard-wrapped at
    this stage; unwrapping happens later so mode converters can inspect
    structure first."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip leading ⏺ bullet and any indent in front of it
    text = re.sub(r"^[ \t]*⏺[ \t]*", "", text, flags=re.MULTILINE)

    lines = text.split("\n")
    blocks: List[Block] = []
    buf: List[str] = []
    in_fence = False
    fence_marker = ""
    fence_indent = 0

    def flush_para():
        if buf:
            blocks.append(("para", buf.copy()))
            buf.clear()

    for raw in lines:
        stripped = raw.strip()

        # Fenced code block handling (``` or ~~~)
        fence_match = re.match(r"^([ \t]*)(```+|~~~+)", raw)
        if fence_match and not in_fence:
            flush_para()
            in_fence = True
            fence_indent = len(fence_match.group(1))
            fence_marker = fence_match.group(2)
            buf.append(raw[fence_indent:])
            continue
        if in_fence:
            # Dedent inner code by the fence's own indent (handles Claude's 2-sp indent)
            dedented = raw[fence_indent:] if raw[:fence_indent].strip() == "" else raw
            buf.append(dedented)
            if re.match(rf"^{re.escape(fence_marker)}[ \t]*$", dedented):
                blocks.append(("code", buf.copy()))
                buf.clear()
                in_fence = False
                fence_marker = ""
                fence_indent = 0
            continue

        # Blank line → paragraph break
        if not stripped:
            flush_para()
            continue

        # Horizontal rule / separator
        if re.match(r"^[-=*_]{3,}$", stripped):
            flush_para()
            blocks.append(("sep", [stripped]))
            continue

        buf.append(stripped)

    if in_fence and buf:
        blocks.append(("code", buf))
    else:
        flush_para()

    return blocks


def is_list_item(line: str) -> bool:
    return bool(re.match(r"^(\s*)([-*+]|\d+\.)\s+", line))


def is_table_row(line: str) -> bool:
    return bool(re.match(r"^\|", line))


# Claude Code soft-wraps lines near this character width. Lines shorter than
# this were intentionally broken by the author, not by the wrapping engine.
_WRAP_THRESHOLD = 72


def _is_block_start(line: str) -> bool:
    """Return True if this line looks like the start of a new logical block
    (not a continuation of a soft-wrapped sentence)."""
    # List items
    if is_list_item(line):
        return True
    # Table rows
    if is_table_row(line):
        return True
    # Headers
    if re.match(r"^#{1,6}\s", line):
        return True
    # Blockquote start
    if line.startswith("> "):
        return True
    # Unicode bullets (•, ▪, ▸, ◦, etc.)
    if line and line[0] in "•▪▸◦◆◇►▷‣⁃":
        return True
    # Bold/italic label at start of line: *Word:* or **Word:** patterns
    # These are definition-style labels that should always start a new line
    # Matches: *What:* ..., **Why:** ..., *Focus Areas:*, _How:_ etc.
    if re.match(r"^(\*{1,2}|_{1,2})[^*_]+:\1", line):
        return True
    return False


def unwrap_paragraph(lines: List[str]) -> List[str]:
    """Join soft-wrapped lines within a paragraph into logical lines.

    Key heuristic: Claude Code wraps at ~76-80 chars. If the previous line is
    shorter than _WRAP_THRESHOLD, the line break was intentional and we preserve
    it. Only lines that are long enough to have been soft-wrapped get joined
    with the next line.

    Block-start markers (list items, headers, blockquotes, bullets) always
    start a new logical line regardless of previous line length.

    Blockquote continuation markers (leading `> `) are stripped before joining
    so a multi-line blockquote becomes a single `> ...` line."""
    if not lines:
        return []
    logical: List[str] = []
    current = ""
    current_is_quote = False
    for ln in lines:
        # Blockquote continuation: join if we're already in a quote
        # (must check before _is_block_start since `> ` is a block-start marker)
        if current_is_quote and ln.startswith(">"):
            cont = re.sub(r"^>\s?", "", ln)
            current += " " + cont
            continue
        # Block-start markers always begin a new logical line
        if _is_block_start(ln):
            if current:
                logical.append(current)
            current = ln
            current_is_quote = ln.startswith("> ")
            continue
        # The core heuristic: only join if the previous line was long enough
        # to have been soft-wrapped by Claude Code's line wrapping.
        # Exception: continuation of a list item (current line is indented text
        # after a list item marker) should always join regardless of length,
        # because list items are often short with wrapped content below.
        prev_is_list = current and is_list_item(current)
        prev_long = current and len(current.rstrip()) >= _WRAP_THRESHOLD
        if current and (prev_long or prev_is_list):
            current += " " + ln
        elif current:
            # Previous line was short → intentional break → new logical line
            logical.append(current)
            current = ln
            current_is_quote = ln.startswith("> ")
        else:
            current = ln
            current_is_quote = ln.startswith("> ")
    if current:
        logical.append(current)
    return logical


# ---------- mode: md (default) ----------

def render_md(blocks: List[Block]) -> str:
    out: List[str] = []
    for kind, content in blocks:
        if kind == "code":
            out.append("\n".join(content))
        elif kind == "sep":
            out.append(content[0])
        else:
            logical = unwrap_paragraph(content)
            out.append("\n".join(logical))
    return "\n\n".join(out) + "\n"


# ---------- mode: slack ----------

# Slack mrkdwn:
#   *bold*, _italic_, ~strike~, `code`, ```block```, <url|label>
#   Headers: no native header syntax → bold the line.
#   Lists: Slack renders `-` and `•` as bullets.

_BOLD_SENTINEL = "\x00B\x00"


def md_inline_to_slack(text: str) -> str:
    # Keep Markdown links as-is — Slack's rich editor handles [text](url) on paste.
    # The <url|text> format is for API/webhooks, not the composer.
    # Stash bold with sentinels so the italic pass can't re-consume it
    text = re.sub(
        r"\*\*(.+?)\*\*",
        lambda m: f"{_BOLD_SENTINEL}{m.group(1)}{_BOLD_SENTINEL}",
        text,
    )
    text = re.sub(
        r"__([^_\n]+)__",
        lambda m: f"{_BOLD_SENTINEL}{m.group(1)}{_BOLD_SENTINEL}",
        text,
    )
    # Italic: *x* → _x_
    text = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])", r"_\1_", text)
    # (Markdown _x_ italic already matches Slack italic syntax.)
    # Restore bold as Slack bold *x*
    text = text.replace(_BOLD_SENTINEL, "*")
    # Strikethrough: ~~x~~ → ~x~
    text = re.sub(r"~~([^~\n]+)~~", r"~\1~", text)
    return text


def _is_table_separator(line: str) -> bool:
    """Match table separator rows like |------|--------|-------|"""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return False
    # Each cell between pipes must be only dashes, colons, spaces (alignment markers)
    cells = stripped.strip("|").split("|")
    return all(re.match(r"^[\s:=-]+$", c) and "-" in c for c in cells)


def _table_to_code_block(lines: List[str]) -> str:
    """Convert Markdown table rows into a padded monospace code block for Slack."""
    # Parse cells from each row, skip separator rows
    rows: List[List[str]] = []
    for line in lines:
        if _is_table_separator(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)

    if not rows:
        return "\n".join(lines)

    # Calculate column widths
    num_cols = max(len(r) for r in rows)
    col_widths = [0] * num_cols
    for row in rows:
        for i, cell in enumerate(row):
            if i < num_cols:
                col_widths[i] = max(col_widths[i], len(cell))

    # Build padded rows
    formatted: List[str] = []
    for ri, row in enumerate(rows):
        padded = []
        for i in range(num_cols):
            cell = row[i] if i < len(row) else ""
            padded.append(cell.ljust(col_widths[i]))
        formatted.append("  ".join(padded))
        # Add a separator after the header row
        if ri == 0:
            formatted.append("  ".join("-" * w for w in col_widths))

    return "```\n" + "\n".join(formatted) + "\n```"


def render_slack(blocks: List[Block]) -> str:
    out: List[str] = []
    for kind, content in blocks:
        if kind == "code":
            joined = "\n".join(content)
            # Strip language hint on opening fence: ```python → ```
            joined = re.sub(r"^```[a-zA-Z0-9_+-]*", "```", joined)
            out.append(joined)
        elif kind == "sep":
            out.append("────────")
        else:
            logical = unwrap_paragraph(content)

            # Check if this block is entirely table rows
            if logical and all(is_table_row(l) for l in logical):
                out.append(_table_to_code_block(logical))
                continue

            # Mixed block: split table rows out from non-table lines
            rendered: List[str] = []
            table_buf: List[str] = []

            def flush_table():
                if table_buf:
                    rendered.append(_table_to_code_block(table_buf))
                    table_buf.clear()

            for line in logical:
                if is_table_row(line):
                    table_buf.append(line)
                    continue
                flush_table()
                m = re.match(r"^(#{1,6})\s+(.*)$", line)
                if m:
                    rendered.append(f"*{md_inline_to_slack(m.group(2))}*")
                    continue
                if line.startswith("> "):
                    rendered.append("> " + md_inline_to_slack(line[2:]))
                    continue
                rendered.append(md_inline_to_slack(line))
            flush_table()
            out.append("\n".join(rendered))
    return "\n\n".join(out) + "\n"


# ---------- mode: plain ----------

def md_inline_to_plain(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1 (\2)", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])", r"\1", text)
    text = re.sub(r"(?<![_\w])_([^_\n]+?)_(?![_\w])", r"\1", text)
    text = re.sub(r"~~([^~\n]+)~~", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    return text


def render_plain(blocks: List[Block]) -> str:
    out: List[str] = []
    for kind, content in blocks:
        if kind == "code":
            inner = content[1:-1] if len(content) >= 2 else content
            out.append("\n".join(inner))
        elif kind == "sep":
            out.append("—" * 40)
        else:
            logical = unwrap_paragraph(content)
            rendered: List[str] = []
            for line in logical:
                m = re.match(r"^(#{1,6})\s+(.*)$", line)
                if m:
                    rendered.append(md_inline_to_plain(m.group(2)))
                    continue
                if line.startswith("> "):
                    rendered.append("> " + md_inline_to_plain(line[2:]))
                    continue
                rendered.append(md_inline_to_plain(line))
            out.append("\n".join(rendered))
    return "\n\n".join(out) + "\n"


# ---------- mode: html ----------

def md_inline_to_html(text: str) -> str:
    text = htmllib.escape(text)
    # Stash inline code so its contents aren't further processed
    code_slots: List[str] = []

    def _stash_code(m):
        code_slots.append(m.group(1))
        return f"\x00CODE{len(code_slots) - 1}\x00"

    text = re.sub(r"`([^`\n]+)`", _stash_code, text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_\n]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])", r"<em>\1</em>", text)
    text = re.sub(r"(?<![_\w])_([^_\n]+?)_(?![_\w])", r"<em>\1</em>", text)
    text = re.sub(r"~~([^~\n]+)~~", r"<del>\1</del>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', text)
    for i, c in enumerate(code_slots):
        text = text.replace(f"\x00CODE{i}\x00", f"<code>{c}</code>")
    return text


def _is_ordered(line: str) -> bool:
    return bool(re.match(r"^\s*\d+\.\s", line))


def _is_unordered(line: str) -> bool:
    return bool(re.match(r"^\s*[-*+]\s", line))


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^\s*([-*+]|\d+\.)\s+", "", line)


def render_html(blocks: List[Block]) -> str:
    out: List[str] = []
    for kind, content in blocks:
        if kind == "code":
            inner = content[1:-1] if len(content) >= 2 else content
            lang_match = (
                re.match(r"^[ \t]*```+([a-zA-Z0-9_+-]*)", content[0]) if content else None
            )
            lang = lang_match.group(1) if lang_match else ""
            code_html = htmllib.escape("\n".join(inner))
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{code_html}</code></pre>")
            continue
        if kind == "sep":
            out.append("<hr>")
            continue

        logical = unwrap_paragraph(content)

        # All list items? → <ul> / <ol>
        if logical and all(_is_ordered(l) or _is_unordered(l) for l in logical):
            ordered = _is_ordered(logical[0])
            tag = "ol" if ordered else "ul"
            items = "\n".join(
                f"  <li>{md_inline_to_html(_strip_list_marker(l))}</li>" for l in logical
            )
            out.append(f"<{tag}>\n{items}\n</{tag}>")
            continue

        # Single-line header
        if len(logical) == 1:
            m = re.match(r"^(#{1,6})\s+(.*)$", logical[0])
            if m:
                level = len(m.group(1))
                out.append(f"<h{level}>{md_inline_to_html(m.group(2))}</h{level}>")
                continue

        # Blockquote paragraph
        if logical and all(l.startswith("> ") for l in logical):
            inner_text = " ".join(l[2:] for l in logical)
            out.append(f"<blockquote><p>{md_inline_to_html(inner_text)}</p></blockquote>")
            continue

        # Table block → <table>
        if logical and all(is_table_row(l) for l in logical):
            rows: List[List[str]] = []
            for tl in logical:
                if _is_table_separator(tl):
                    continue
                cells = [c.strip() for c in tl.strip().strip("|").split("|")]
                rows.append(cells)
            if rows:
                header = rows[0]
                body = rows[1:]
                thead = "    <tr>" + "".join(
                    f"<th>{md_inline_to_html(c)}</th>" for c in header
                ) + "</tr>"
                tbody_rows = []
                for row in body:
                    tbody_rows.append("    <tr>" + "".join(
                        f"<td>{md_inline_to_html(c)}</td>" for c in row
                    ) + "</tr>")
                tbody = "\n".join(tbody_rows)
                out.append(f"<table>\n  <thead>\n{thead}\n  </thead>\n  <tbody>\n{tbody}\n  </tbody>\n</table>")
                continue

        joined = " ".join(logical)
        out.append(f"<p>{md_inline_to_html(joined)}</p>")

    return "\n".join(out) + "\n"


# ---------- dispatch ----------

RENDERERS = {
    "md": render_md,
    "slack": render_slack,
    "plain": render_plain,
    "html": render_html,
}


def reformat(text: str, mode: str = "md") -> str:
    blocks = parse_blocks(text)
    renderer = RENDERERS.get(mode, render_md)
    return renderer(blocks)


# ---------- CLI ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reformat Claude Code output for clean pasting.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Modes:\n"
            "  md     (default) keep Markdown, just dedent + unwrap\n"
            "  slack  convert to Slack mrkdwn (bold, links, headers)\n"
            "  plain  strip Markdown syntax, keep plain text\n"
            "  html   convert to HTML (paragraphs, lists, inline formatting)\n"
        ),
    )
    parser.add_argument(
        "-m", "--mode",
        default="md",
        choices=list(RENDERERS.keys()),
        help="output format (default: md)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print result to stdout instead of writing to clipboard",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="'-' to read from stdin (implies --stdout)",
    )
    args = parser.parse_args()

    read_stdin = args.input == "-"
    to_stdout = args.stdout or read_stdin

    if read_stdin:
        source = sys.stdin.read()
    else:
        source = get_clipboard()

    result = reformat(source, args.mode)

    if to_stdout:
        sys.stdout.write(result)
    else:
        set_clipboard(result)
        sys.stderr.write(f"Reformatted ({args.mode}) and copied to clipboard.\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
