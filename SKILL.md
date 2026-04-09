---
name: clip
description: Take the most recent prior assistant message in this conversation, strip Claude Code's ⏺ bullet and 2-space indent, unwrap hard-wrapped paragraphs, and copy the result to the macOS clipboard in a target format (Markdown, Slack mrkdwn, plain text, or HTML). Use when the user says "/clip", "clip that", "copy that for Slack", "copy as plain text", "copy as html", "copy the last message", or wants to grab Claude's prior output in paste-friendly form.
argument-hint: "[md | slack | plain | html]  (default: md)"
---

# Clip — Clean & Copy the Last Claude Message

Grabs the **most recent prior assistant message** in the current conversation, runs it through the bundled reformatter (`scripts/reformat.py` inside this skill directory), and replaces the macOS clipboard with the cleaned text in the requested format.

Designed for the case where the user wants to paste Claude's output somewhere else (doc, email, Slack, Linear, a blog post) without the `⏺` bullet and 2-space indent that Claude Code applies to its rendered output.

## When to Use

- User types `/clip`, `/clip slack`, `/clip plain`, `/clip html`
- User says "clip that", "clip the last response", "copy that cleanly", "grab the last message"
- User wants to paste Claude's prior output somewhere specific ("copy that for Slack", "copy as plain text for email", "give me the HTML version")

## Modes

| Mode    | What it does                                                                         | Typical destination            |
|---------|--------------------------------------------------------------------------------------|--------------------------------|
| `md`    | (default) Strip ⏺/indent, unwrap paragraphs, **keep Markdown as-is**                  | Linear, GitHub, Notion, docs   |
| `slack` | Convert Markdown → Slack mrkdwn (`**bold**`→`*bold*`, `[x](url)`→`<url|x>`, etc.)    | Slack messages, threads        |
| `plain` | Strip all Markdown syntax, keep the pure prose                                       | Email, SMS, plain-text notes   |
| `html`  | Convert Markdown → HTML (paragraphs, lists, headers, inline formatting)              | CMS, blog editors, email HTML  |

**Default mode is `md`** — if the user invokes `/clip` with no mode argument, use `md`.

**How to interpret user intent:**
- `/clip` or `/clip md` → `md`
- `/clip slack` or "copy that for Slack" or "Slack mrkdwn" → `slack`
- `/clip plain` or `/clip email` or "plain text" or "strip formatting" → `plain`
- `/clip html` or "HTML version" → `html`

## What "the last message" means

"The last message" = **the most recent assistant (Claude) message in the conversation immediately before the user invoked `/clip`**. Not the user's message. Not an earlier assistant message. The single most recent assistant turn's full prose content.

If `/clip` is invoked as the very first turn (no prior assistant message exists), tell the user there's nothing to clip and stop.

## Requirements

- **Platform:** macOS (uses `pbcopy`). On Linux/Windows the pipe target would need to change.
- **Python 3** on `PATH` (the reformatter is pure stdlib — no pip dependencies).
- **Bundled script:** `scripts/reformat.py` inside this skill directory. Self-contained; do not rely on any script outside the skill directory.

## How to Execute

### Step 1 — Resolve the bundled reformatter path

The reformatter lives at `scripts/reformat.py` **relative to this SKILL.md file**. Skills can be installed anywhere on a user's machine, so resolve the absolute path at runtime rather than hardcoding a user-specific path.

When Claude Code loads this skill, the absolute path to `SKILL.md` is visible to you in context. Derive the script path as `<dirname of SKILL.md>/scripts/reformat.py`. If that isn't resolvable, fall back to:

```bash
SKILL_DIR="$(dirname "$(find "$HOME" -type f -name SKILL.md -path '*/skills/clip/SKILL.md' 2>/dev/null | head -1)")"
REFORMAT="$SKILL_DIR/scripts/reformat.py"
```

### Step 2 — Pipe the prior message through the reformatter into the clipboard

Use a single Bash call with a **quoted heredoc** so the message text is passed verbatim without shell expansion. Pass the mode via `-m`:

```bash
cat <<'CLIP_EOF' | python3 /absolute/path/to/skill/scripts/reformat.py -m <MODE> - | pbcopy
<paste the full text of your previous assistant message here, verbatim>
CLIP_EOF
```

Replace `<MODE>` with `md`, `slack`, `plain`, or `html` based on what the user asked for. If the user didn't specify, use `md`.

Rules:
- Use the **quoted** heredoc form (`<<'CLIP_EOF'`) so `$`, backticks, and backslashes in the message stay literal.
- If `CLIP_EOF` appears inside the message body, pick a different unique delimiter (e.g. `CLIP_EOF_7F3A`).
- Pass the message **verbatim**. Do not trim, summarize, rewrite, or otherwise modify the content — the script handles all whitespace and formatting normalization.
- The script reads from stdin (`-`) and prints to stdout, which is then piped to `pbcopy` to replace the clipboard.

### Step 3 — Confirm

Reply with a single short line that includes the mode:

```
Clipped (slack). Paste with ⌘V.
```

or

```
Clipped (md). Paste with ⌘V.
```

Nothing more. Do not echo the cleaned output back to the chat unless the user explicitly asks to see it.

## What NOT to do

- Do not summarize or paraphrase the previous message.
- Do not edit the previous message before piping it.
- Do not attempt to do the Markdown→Slack/HTML/plain conversion in your head — always pipe through the script. The script is deterministic; ad-hoc LLM conversion is not.
- Do not include tool-call blocks, tool results, `<system-reminder>` content, or user messages in the clipped text.
- Do not hardcode paths like `~/bin/claude-reformat.py` or `~/octave/...`.
- Do not re-print the cleaned result to the chat by default.

## What the reformatter does

`scripts/reformat.py` is a ~400-line pure-stdlib Python script. Behavior:

1. Normalize CRLF → LF
2. Strip any leading `⏺` marker from lines
3. Parse into typed blocks: paragraphs, fenced code, separators
4. Dedent fenced code blocks by the fence's own indent (so Claude's 2-sp indent is removed from code)
5. Unwrap soft-wrapped paragraph lines (join with spaces, but start a new logical line on list items)
6. Unwrap blockquote continuations (`> line1\n> line2` → `> line1 line2`)
7. Apply the mode-specific renderer:
   - **md:** emit as-is (Markdown preserved)
   - **slack:** `**bold**`→`*bold*`, `*italic*`→`_italic_`, `[x](url)`→`<url|x>`, headers→bold lines, `~~x~~`→`~x~`
   - **plain:** strip `**`, `*`, `_`, `` ` ``, `~~`, unwrap links as `label (url)`, headers become plain lines
   - **html:** emit `<h1>..<h6>`, `<p>`, `<ul>`/`<ol>`, `<li>`, `<strong>`, `<em>`, `<code>`, `<pre><code>`, `<blockquote>`, `<hr>`, `<a href>`, `<del>`, all HTML-escaped

CLI modes:
- `reformat.py [-m MODE]` — read `pbpaste`, write cleaned text back via `pbcopy`
- `reformat.py [-m MODE] --stdout` — read `pbpaste`, print to stdout
- `reformat.py [-m MODE] -` — read from stdin, print to stdout ← **used by this skill**

## Example

User's prior assistant turn was:

```
⏺ What Else

  # Key insight

  The **qual-doctor** skill has a [hidden](https://x.com) duplicate of the
  ads-resonance prediction card system, and neither one knows about the
  other yet.

  - First item that wraps across
    multiple lines
  - Second item
```

User: `/clip slack`

Skill runs:

```bash
cat <<'CLIP_EOF' | python3 /Users/somebody/.claude/skills/clip/scripts/reformat.py -m slack - | pbcopy
⏺ What Else

  # Key insight

  The **qual-doctor** skill has a [hidden](https://x.com) duplicate of the
  ads-resonance prediction card system, and neither one knows about the
  other yet.

  - First item that wraps across
    multiple lines
  - Second item
CLIP_EOF
```

Clipboard now contains:

```
What Else

*Key insight*

The *qual-doctor* skill has a <https://x.com|hidden> duplicate of the ads-resonance prediction card system, and neither one knows about the other yet.

- First item that wraps across multiple lines
- Second item
```

Skill replies: `Clipped (slack). Paste with ⌘V.`
