# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small Markdown renderer for Tk text widgets.

Tk's ``Text`` widget has no Markdown support, so LLM answers arrive looking
like raw source (``**bold**``, ``## headings``, backtick fences, ...). This
module parses the answer with markdown-it-py and inserts it as *tagged* text:
headings, bold/italic/strikethrough, inline and fenced code, nested lists,
block quotes, clickable links, horizontal rules and simple tables.

The parser only runs once per answer, so rendering cost is negligible.
"""

from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont
import webbrowser

from markdown_it import MarkdownIt

_HEADING_SIZES = (10, 7, 4, 2, 1, 0)
_TABLE_MARKUP = re.compile(r"[*_`]+")


def _plain(text: str) -> str:
    """Strip the most common inline markers for table cells."""
    return _TABLE_MARKUP.sub("", text).strip()


def _configure_tags(widget: tk.Text) -> None:
    try:
        base = tkfont.Font(font=widget.cget("font"))
        family = base.actual("family")
        size = int(base.actual("size"))
    except Exception:  # no Tk root (tests) or odd font spec
        family, size = "Arial", 12

    widget.tag_configure("md_strong", font=(family, size, "bold"))
    widget.tag_configure("md_em", font=(family, size, "italic"))
    widget.tag_configure("md_s", overstrike=True)
    widget.tag_configure(
        "md_code_inline", font="TkFixedFont", background="#ececec"
    )
    widget.tag_configure(
        "md_code_block",
        font="TkFixedFont",
        background="#f4f4f4",
        lmargin1=12,
        lmargin2=12,
        spacing1=2,
        spacing3=2,
    )
    widget.tag_configure("md_hr", foreground="#999999")
    widget.tag_configure("md_table_head", font=(family, size, "bold"))
    widget.tag_configure("md_table_rule", foreground="#999999")

    for level, bump in enumerate(_HEADING_SIZES, 1):
        widget.tag_configure(
            f"md_h{level}",
            font=(family, size + bump, "bold"),
            spacing1=6,
            spacing3=3,
        )


class _Renderer:
    """Walk a markdown-it token stream and emit tagged text segments."""

    def __init__(self, widget: tk.Text):
        self.widget = widget
        self._segments: list[tuple[str, tuple[str, ...]]] = []
        self._styles: list[str] = []
        self._lists: list[dict] = []
        self._quote_depth = 0
        self._link_count = 0

    # -- segment helpers -------------------------------------------------

    def _emit(self, text: str, extra: tuple[str, ...] = ()) -> None:
        if not text:
            return
        tags = tuple(self._styles) + tuple(extra)
        if self._segments and self._segments[-1][1] == tags:
            prev_text, _ = self._segments[-1]
            self._segments[-1] = (prev_text + text, tags)
        else:
            self._segments.append((text, tags))

    def _tail(self) -> str:
        return self._segments[-1][0] if self._segments else ""

    def _ends_with(self, suffix: str) -> bool:
        return self._tail().endswith(suffix)

    def _blank_line(self) -> None:
        """Emit at most one blank line, without stacking newlines."""
        if not self._ends_with("\n\n"):
            self._emit("\n" if self._ends_with("\n") else "\n\n")

    def _pop(self, prefix: str) -> None:
        for i in range(len(self._styles) - 1, -1, -1):
            if self._styles[i].startswith(prefix):
                del self._styles[i]
                return

    def _layout_tag(self) -> str:
        """Tag with indentation for the current list/quote nesting."""
        depth = max(0, len(self._lists) - 1)
        indent = self._quote_depth * 16 + depth * 18
        tag = f"md_layout_{self._quote_depth}_{depth}"
        options = {
            "lmargin1": 8 + indent,
            "lmargin2": 22 + indent,
        }
        if self._quote_depth:
            options["foreground"] = "#555555"
        try:
            self.widget.tag_configure(tag, **options)
        except Exception:  # pragma: no cover - defensive for stub widgets
            pass
        return tag

    # -- token handling --------------------------------------------------

    def render(self, tokens) -> None:
        i = 0
        while i < len(tokens):
            token = tokens[i]
            kind = token.type

            if kind == "table_open":
                rows, close = self._collect_table(tokens, i)
                self._emit_table(rows)
                i = close + 1
                continue

            if kind == "heading_open":
                self._styles.append(self._layout_tag())
                self._styles.append(f"md_h{token.tag[1:]}")
            elif kind == "heading_close":
                self._pop("md_h")
                self._pop("md_layout_")
                self._emit("\n\n")
            elif kind == "paragraph_open":
                self._styles.append(self._layout_tag())
            elif kind == "paragraph_close":
                self._pop("md_layout_")
                self._emit("\n" if self._lists else "\n\n")
            elif kind in ("bullet_list_open", "ordered_list_open"):
                ordered = kind.startswith("ordered")
                start = 1
                if ordered:
                    try:
                        start = int(token.attrGet("start") or 1)
                    except (TypeError, ValueError):
                        start = 1
                self._lists.append({"ordered": ordered, "counter": start - 1})
            elif kind in ("bullet_list_close", "ordered_list_close"):
                if self._lists:
                    self._lists.pop()
                if not self._lists:
                    self._blank_line()
            elif kind == "list_item_open":
                layout = self._layout_tag()
                current = self._lists[-1] if self._lists else {"ordered": False}
                if current["ordered"]:
                    current["counter"] += 1
                    prefix = f"{current['counter']}. "
                else:
                    prefix = "\u2022  "
                self._emit(prefix, (layout,))
            elif kind == "list_item_close":
                pass
            elif kind == "blockquote_open":
                self._quote_depth += 1
            elif kind == "blockquote_close":
                self._quote_depth = max(0, self._quote_depth - 1)
                self._blank_line()
            elif kind in ("fence", "code_block"):
                self._emit_code(token.content)
            elif kind == "hr":
                self._blank_line()
                self._emit("\u2500" * 60 + "\n\n", ("md_hr",))
            elif kind == "inline":
                self._render_inline(token)

            i += 1

        self._flush()

    def _render_inline(self, token) -> None:
        for child in token.children or ():
            kind = child.type
            if kind == "text":
                self._emit(child.content)
            elif kind == "strong_open":
                self._styles.append("md_strong")
            elif kind == "strong_close":
                self._pop("md_strong")
            elif kind == "em_open":
                self._styles.append("md_em")
            elif kind == "em_close":
                self._pop("md_em")
            elif kind == "s_open":
                self._styles.append("md_s")
            elif kind == "s_close":
                self._pop("md_s")
            elif kind == "code_inline":
                self._emit(child.content, ("md_code_inline",))
            elif kind == "softbreak":
                self._emit(" ")
            elif kind == "hardbreak":
                self._emit("\n")
            elif kind == "link_open":
                href = child.attrGet("href") or ""
                tag = f"md_link_{self._link_count}"
                self._link_count += 1
                try:
                    self.widget.tag_configure(
                        tag, foreground="#0563c1", underline=True
                    )
                    self.widget.tag_bind(
                        tag, "<Button-1>", lambda _e, url=href: webbrowser.open(url)
                    )
                    self.widget.tag_bind(
                        tag,
                        "<Enter>",
                        lambda _e: self.widget.configure(cursor="hand2"),
                    )
                    self.widget.tag_bind(
                        tag, "<Leave>", lambda _e: self.widget.configure(cursor="")
                    )
                except Exception:  # pragma: no cover - stub widgets
                    pass
                self._styles.append(tag)
            elif kind == "link_close":
                self._pop("md_link_")
            elif kind == "image":
                alt = _plain(child.content or child.attrGet("alt") or "image")
                self._emit(f"[{alt}]", ("md_em",))
            # html_inline / unknown tokens are intentionally ignored

    def _emit_code(self, content: str) -> None:
        content = (content or "").rstrip("\n")
        self._blank_line()
        for line in content.split("\n"):
            self._emit(line + "\n", ("md_code_block",))
        self._emit("\n")

    # -- tables ----------------------------------------------------------

    @staticmethod
    def _collect_table(tokens, start: int) -> tuple[list[tuple[list[str], bool]], int]:
        rows: list[tuple[list[str], bool]] = []
        row: list[str] | None = None
        cell: list[str] | None = None
        in_head = False
        i = start + 1
        while i < len(tokens):
            token = tokens[i]
            kind = token.type
            if kind == "table_close":
                break
            if kind == "thead_open":
                in_head = True
            elif kind == "thead_close":
                in_head = False
            elif kind == "tr_open":
                row = []
            elif kind == "tr_close":
                rows.append((row or [], in_head))
                row = None
            elif kind in ("th_open", "td_open"):
                cell = []
            elif kind == "inline" and cell is not None:
                cell.append(_plain(token.content))
            elif kind in ("th_close", "td_close"):
                if row is not None:
                    row.append(" ".join(cell or []).strip())
                cell = None
            i += 1
        return rows, i

    def _emit_table(self, rows: list[tuple[list[str], bool]]) -> None:
        if not rows:
            return
        columns = max(len(row) for row, _ in rows)
        widths = [
            max(len(row[c]) if c < len(row) else 0 for row, _ in rows)
            for c in range(columns)
        ]
        self._blank_line()
        for row, is_head in rows:
            cells = [
                (row[c] if c < len(row) else "").ljust(widths[c])
                for c in range(columns)
            ]
            line = "  ".join(cells).rstrip()
            self._emit(line + "\n", ("md_table_head",) if is_head else ())
            if is_head:
                self._emit(
                    "  ".join("\u2500" * width for width in widths) + "\n",
                    ("md_table_rule",),
                )
        self._blank_line()

    # -- output ----------------------------------------------------------

    def _flush(self) -> None:
        segments = self._segments
        while segments and not segments[0][0].strip("\n"):
            segments.pop(0)
        if segments:
            text, tags = segments[0]
            segments[0] = (text.lstrip("\n"), tags)
        while segments and not segments[-1][0].strip("\n"):
            segments.pop()
        if segments:
            text, tags = segments[-1]
            segments[-1] = (text.rstrip("\n"), tags)

        for text, tags in segments:
            if text:
                self.widget.insert(tk.END, text, tags)


def insert_markdown(widget: tk.Text, text: str) -> None:
    """Render *text* as Markdown into a Tk ``Text`` widget at the end."""
    _configure_tags(widget)
    parser = MarkdownIt("commonmark", {"html": False}).enable(
        ["table", "strikethrough"]
    )
    _Renderer(widget).render(parser.parse(text or ""))
