import pytest
from opening_fenix.core.markdown_renderer import markdown_to_github_html

def test_markdown_empty_and_whitespace():
    assert markdown_to_github_html("") == ""
    assert markdown_to_github_html("   \n\t  ") == ""
    assert markdown_to_github_html(None) == ""

def test_markdown_headings():
    md = "# Heading 1\n## Heading 2\n### Heading 3\n#### Heading 4"
    html = markdown_to_github_html(md)
    assert "Heading 1" in html
    assert "Heading 2" in html
    assert "Heading 3" in html
    assert "Heading 4" in html
    assert '<hr style="height: 1px; border: none; background-color: #d0d7de;' in html

def test_markdown_inlines():
    md = "Text with **bold**, *italic*, ~~strikethrough~~, and `inline_code()`."
    html = markdown_to_github_html(md)
    assert '<strong style="font-weight: 600; color: #1f2328;">bold</strong>' in html
    assert '<em>italic</em>' in html
    assert '<del style="color: #656d76;">strikethrough</del>' in html
    assert 'inline_code()' in html
    assert 'background-color: #eff1f3;' in html
    assert 'font-family: ui-monospace' in html

def test_markdown_links():
    md = "Check [Opening Fenix](https://github.com/Takais-Chess/Opening-Fenix) or raw https://github.com"
    html = markdown_to_github_html(md)
    assert '<a href="https://github.com/Takais-Chess/Opening-Fenix"' in html
    assert 'Opening Fenix</a>' in html
    assert '<a href="https://github.com"' in html

def test_markdown_lists():
    md = """- Item 1
- Item 2
  - Subitem 2.1
  - Subitem 2.2
- [ ] Todo item
- [x] Done item"""
    html = markdown_to_github_html(md)
    assert '<ul style="' in html
    assert 'Item 1</li>' in html
    assert 'Subitem 2.1</li>' in html
    assert '☐ Todo item' in html
    assert '☑ Done item' in html

def test_markdown_code_block():
    md = """```python
def add(a, b):
    return a + b
```"""
    html = markdown_to_github_html(md)
    assert '<pre style="background-color: #f6f8fa;' in html
    assert 'def add(a, b):' in html

def test_markdown_blockquote():
    md = "> This is a note.\n> Second line of note."
    html = markdown_to_github_html(md)
    assert 'border-left: 3px solid #d0d7de;' in html
    assert 'This is a note.<br />Second line of note.' in html

def test_markdown_table():
    md = """| Feature | Status |
| --- | --- |
| Zero-Tremble | Shipped |
| High-DPI | Verified |"""
    html = markdown_to_github_html(md)
    assert '<table style="' in html
    assert '<th style=' in html
    assert 'Feature</th>' in html
    assert '<td style=' in html
    assert 'Zero-Tremble</td>' in html

def test_markdown_escaping():
    md = "Condition: `dev_dx < 0` and value > 95% and `vector<int>`"
    html = markdown_to_github_html(md)
    assert "dev_dx &lt; 0" in html
    assert "&gt; 95%" in html
    assert "vector&lt;int&gt;" in html
