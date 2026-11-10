# SPDX-License-Identifier: AGPL-3.0-or-later
"""Markdown rendering into Tk text widgets (no display needed)."""

from relevantr.gui.markdown_view import insert_markdown


class FakeText:
    """Records what would be inserted into a real Tk Text widget."""

    def __init__(self):
        self.parts: list[tuple[str, tuple[str, ...]]] = []
        self.tags: dict[str, dict] = {}
        self.binds: list[tuple[str, str]] = []

    def cget(self, key):
        return "Arial 12"

    def tag_configure(self, tag, **options):
        self.tags[tag] = options

    def tag_bind(self, tag, sequence, func):
        self.binds.append((tag, sequence))

    def insert(self, index, text, tags=()):
        self.parts.append((text, tuple(tags)))

    @property
    def text(self):
        return "".join(text for text, _ in self.parts)

    @property
    def used_tags(self):
        return {tag for _, tags in self.parts for tag in tags}


def render(markdown: str) -> FakeText:
    widget = FakeText()
    insert_markdown(widget, markdown)
    return widget


def test_markdown_markers_are_not_shown_raw():
    widget = render("# Title\n\nThis is **bold** and *italic* with `code`.\n")
    assert "# Title" not in widget.text
    assert "**" not in widget.text
    assert "`" not in widget.text
    assert "This is bold and italic with code." in widget.text


def test_heading_and_inline_styles_get_tags():
    widget = render("## Section\n\nSome **strong** and *em* text.\n")
    assert "md_h2" in widget.used_tags
    assert "md_strong" in widget.used_tags
    assert "md_em" in widget.used_tags


def test_lists_code_blocks_and_quotes():
    markdown = (
        "- first\n"
        "- second\n\n"
        "```python\nprint('hi')\n```\n\n"
        "> quoted\n"
    )
    widget = render(markdown)
    assert "\u2022  first" in widget.text
    assert "print('hi')" in widget.text
    assert "quoted" in widget.text
    assert "md_code_block" in widget.used_tags


def test_tables_render_as_aligned_text():
    markdown = (
        "| Material | Strength |\n"
        "|----------|----------|\n"
        "| Steel    | 500 MPa  |\n"
    )
    widget = render(markdown)
    assert "Material" in widget.text and "Strength" in widget.text
    assert "Steel" in widget.text and "500 MPa" in widget.text
    assert "md_table_head" in widget.used_tags


def test_links_are_clickable():
    widget = render("See [the paper](https://example.com).\n")
    assert "the paper" in widget.text
    assert "https://example.com" not in widget.text
    link_tags = [tag for tag, _ in widget.binds]
    assert link_tags and all(tag.startswith("md_link_") for tag in link_tags)


def test_plain_text_without_markdown_is_preserved():
    widget = render("Just a normal answer with no markup.")
    assert widget.text == "Just a normal answer with no markup."
