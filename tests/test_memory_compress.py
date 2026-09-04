"""memory_compress: standing sections survive, only the oldest dated log entries are archived,
template comments are not headings, appending a dated section compresses only when needed."""
from datetime import datetime

from memory_compress import append_dated_section, compress_memory, split_sections

HEAD = "---\nagent: DeciderAgent\n---\n\n# Decider — Memory\n\n> conventions\n"
LESSONS = "## Lessons Learned\n- **#gap-chase** never chase a gap.\n- **#priced-kill** kill at K.\n"
PATTERNS = "## Patterns to Watch\n- leaders rolling over.\n"
LOG_HEAD = "## Log\n<!-- template:\n## YYYY-MM-DD #ticker-XYZ #failure-mode\n- what happened\n-->\n"


def _entry(day, size=400):
    return f"## 2026-0{day // 30 + 6}-{day % 30 + 1:02d} #tag\n" + ("- line of lesson text\n" * (size // 22))


def test_split_ignores_headings_inside_comments():
    secs = split_sections(HEAD + LESSONS + LOG_HEAD + _entry(1))
    headings = [h for h, _ in secs if h]
    assert headings == ["## Lessons Learned", "## Log", "## 2026-06-02 #tag"]


def test_compress_archives_oldest_entries_only():
    text = HEAD + LESSONS + PATTERNS + LOG_HEAD + "".join(_entry(d) for d in range(1, 9))
    assert len(text) > 3000
    out = compress_memory(text, 3000)
    assert len(out) <= 3000
    assert "## Lessons Learned" in out and "**#priced-kill**" in out and "## Patterns to Watch" in out
    assert "<!-- template:" in out and "-->" in out
    assert "## 2026-06-02 #tag" not in out and "## 2026-06-09 #tag" in out        # oldest gone, newest kept
    assert "log entries archived" in out
    # standing sections cannot be archived: an oversize text with no dated entries is returned as is
    assert compress_memory(HEAD + LESSONS * 50, 500) == HEAD + LESSONS * 50


def test_append_dated_section():
    base = HEAD + LESSONS + LOG_HEAD + _entry(1)
    out = append_dated_section(base, "- 1. REGIME — If RISK-OFF, PASS; otherwise fall through.", today=datetime(2026, 9, 3))
    assert out.endswith("## 2026-09-03\n- 1. REGIME — If RISK-OFF, PASS; otherwise fall through.")
    assert "## Lessons Learned" in out
    assert append_dated_section(base, "", today=datetime(2026, 9, 3)) == base.strip()
    small = append_dated_section(base, "- x", today=datetime(2026, 9, 3), max_chars=len(base) - 200)
    assert "## Lessons Learned" in small and "## 2026-09-03" in small and "## 2026-06-02" not in small
