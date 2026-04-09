# claude-clip

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that copies Claude's last response to your clipboard, cleaned up and formatted for wherever you're pasting it.

Claude Code wraps its output with `⏺` bullets and 2-space indentation. That's fine in the terminal, but messy when you paste into Slack, Linear, a doc, or an email. `/clip` strips the noise and reformats for your target.

## Modes

| Command | What it does | Paste into |
|---------|-------------|------------|
| `/clip` | Strip bullets/indent, keep Markdown | Linear, GitHub, Notion, docs |
| `/clip slack` | Convert to Slack mrkdwn (bold, italic, tables as code blocks) | Slack messages and threads |
| `/clip plain` | Strip all formatting, pure prose | Email, SMS, plain text |
| `/clip html` | Convert to HTML (`<p>`, `<table>`, `<ul>`, etc.) | CMS, blog editors, email HTML |

## Install

Clone this repo into your Claude Code skills directory:

```bash
git clone https://github.com/octavehq/claude-clip.git ~/.claude/skills/clip
```

That's it. Type `/clip` in Claude Code after any response.

## Requirements

- macOS (uses `pbcopy` for clipboard)
- Python 3 (pure stdlib, no pip dependencies)

## What it handles

- **Bold**, *italic*, ~~strikethrough~~, `inline code`, [links](https://example.com)
- Headers, blockquotes, ordered and unordered lists
- Fenced code blocks (with language hints stripped for Slack)
- Markdown tables (converted to aligned monospace code blocks for Slack, `<table>` for HTML)
- Separators (`---`)
- Nested formatting (`**bold with *italic* inside**`)
- Unicode, emoji, CJK characters
- Shell-dangerous characters (`$`, backticks, backslashes) preserved safely via quoted heredoc

## How it works

The skill tells Claude to pipe its last message through a bundled Python reformatter (`scripts/reformat.py`) into `pbcopy`:

```bash
cat <<'CLIP_EOF' | python3 /path/to/scripts/reformat.py -m slack - | pbcopy
<Claude's last message, verbatim>
CLIP_EOF
```

The reformatter:
1. Normalizes line endings
2. Strips `⏺` bullet markers
3. Parses into typed blocks (paragraphs, code, tables, separators)
4. Unwraps soft-wrapped lines
5. Applies the mode-specific renderer

The script is deterministic — no LLM involved in the formatting step.

## Tests

```bash
cd scripts
python3 -m unittest test_reformat -v
```

84 tests covering all four modes, edge cases (empty input, unclosed formatting, shell-dangerous characters), Unicode, tables, and a comprehensive end-to-end fixture.

## Anatomy of a Claude Code skill

If you're building your own skill, this repo is a minimal working example of the pattern:

```
claude-clip/
├── SKILL.md              # Instructions Claude follows when the skill is invoked
├── scripts/
│   ├── reformat.py       # Deterministic script that does the actual work
│   └── test_reformat.py  # Unit tests (pure stdlib, no pytest needed)
├── .gitignore
└── README.md
```

The key idea: **SKILL.md tells Claude what to do, the script does the work deterministically.** Claude handles intent parsing ("the user wants Slack format") and message extraction; the script handles formatting without any LLM ambiguity.

---

## Shameless plug

If you're copying a lot of Claude output, there's a good chance you're building GTM content — emails, battlecards, call prep, competitive intel, campaign copy.

Tired of Claude not knowing about your business? Want reliable context that your GTM team and AI agents can trust and control?

**[Octave](https://octavehq.com)** gives your AI a structured knowledge base of your products, personas, competitors, proof points, and messaging — so every output is grounded in what's actually true about your business.

Check out the open-source Claude Code plugin: **[lfgtm](https://github.com/octavehq/lfgtm)**
