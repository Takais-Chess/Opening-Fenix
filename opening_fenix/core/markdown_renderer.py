"""
Markdown renderer providing authentic GitHub-flavored HTML formatting
specifically optimized for PyQt6 rich-text rendering widgets (QTextBrowser / QTextEdit).
"""

import re
import html
from typing import Optional


def markdown_to_github_html(md_text: Optional[str]) -> str:
    """
    Converts GitHub-flavored Markdown text into authentic GitHub-styled HTML
    specifically optimized for PyQt6 rich-text rendering widgets.

    Features:
    - GitHub typography stack and color palette (#1f2328, #eff1f3, #d0d7de, #0969da)
    - H1/H2 headings with bottom divider lines (<hr>)
    - Unordered/ordered lists with nested levels and checkbox task lists
    - Code pills with light grey background, monospace font, and rounded padding
    - Fenced code blocks with background container and border
    - Blockquotes with left border indicator
    - Markdown tables with alternating row shading
    - Bold, italic, strikethrough, and clickable hyperlinks
    - Safe HTML entity escaping to preserve special characters (e.g. '<', '>', '&')
    """
    if not md_text or not md_text.strip():
        return ""

    lines = md_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def format_inlines(text: str) -> str:
        inline_codes = []

        def save_inline_code(match):
            code_content = match.group(1)
            escaped = html.escape(code_content)
            inline_codes.append(
                f'<span style="background-color: #eff1f3; color: #1f2328; '
                f'font-family: ui-monospace, SFMono-Regular, Consolas, monospace; '
                f'font-size: 11px; padding: 2px 4.5px; border-radius: 4px;">{escaped}</span>'
            )
            return f"@@INLINE_CODE_{len(inline_codes) - 1}@@"

        # 1. Protect inline code first so its contents are untouched by formatting rules
        text = re.sub(r'`([^`\n]+)`', save_inline_code, text)

        # 2. Escape HTML entities in non-code parts
        parts = text.split("@@INLINE_CODE_")
        escaped_parts = []
        for idx, part in enumerate(parts):
            if idx == 0:
                escaped_parts.append(html.escape(part))
            else:
                m = re.match(r'^(\d+@@)(.*)$', part, re.DOTALL)
                if m:
                    escaped_parts.append(m.group(1) + html.escape(m.group(2)))
                else:
                    escaped_parts.append(html.escape(part))
        text = "@@INLINE_CODE_".join(escaped_parts)

        # 3. Markdown links: [text](url)
        text = re.sub(
            r'\[([^\]]+)\]\((https?://[^)\s]+)\)',
            r'<a href="\2" style="color: #0969da; text-decoration: none; font-weight: 500;">\1</a>',
            text
        )

        # 4. Standalone URLs (not already part of an href attribute)
        text = re.sub(
            r'(?<!href=")(?<!">)(https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+)',
            r'<a href="\1" style="color: #0969da; text-decoration: none; font-weight: 500;">\1</a>',
            text
        )

        # 5. Bold & Italic combinations
        text = re.sub(r'\*\*\*([^\*\n]+)\*\*\*', r'<strong style="font-weight: 600; color: #1f2328;"><em>\1</em></strong>', text)
        text = re.sub(r'___([^_\n]+)___', r'<strong style="font-weight: 600; color: #1f2328;"><em>\1</em></strong>', text)

        # 6. Bold: **text** or __text__
        text = re.sub(r'\*\*([^\*\n]+)\*\*', r'<strong style="font-weight: 600; color: #1f2328;">\1</strong>', text)
        text = re.sub(r'__([^_\n]+)__', r'<strong style="font-weight: 600; color: #1f2328;">\1</strong>', text)

        # 7. Italic: *text* or _text_
        text = re.sub(r'\*([^\*\s\n][^\*\n]*?)\*', r'<em>\1</em>', text)
        text = re.sub(r'(?<!\w)_([^_\s\n][^_\n]*?)_(?!\w)', r'<em>\1</em>', text)

        # 8. Strikethrough: ~~text~~
        text = re.sub(r'~~([^~\n]+)~~', r'<del style="color: #656d76;">\1</del>', text)

        # 9. Restore inline code placeholders
        for idx, code_html in enumerate(inline_codes):
            text = text.replace(f"@@INLINE_CODE_{idx}@@", code_html)

        return text

    output_html = []
    in_code_block = False
    current_code_block = []
    list_stack = []
    in_blockquote = False
    blockquote_lines = []
    in_table = False
    table_rows = []

    def close_all_lists():
        nonlocal list_stack
        while list_stack:
            ltype, _ = list_stack.pop()
            output_html.append(f"</{ltype}>")

    def close_blockquote():
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote:
            content = "<br />".join(blockquote_lines)
            output_html.append(
                f'<div style="border-left: 3px solid #d0d7de; padding: 4px 0 4px 12px; '
                f'margin: 8px 0; color: #656d76; font-size: 13px;">{content}</div>'
            )
            in_blockquote = False
            blockquote_lines = []

    def close_table():
        nonlocal in_table, table_rows
        if in_table:
            table_html = ['<table style="border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 12px;">']
            for row_idx, row in enumerate(table_rows):
                is_header = (row_idx == 0)
                bg = '#f6f8fa' if is_header else ('#ffffff' if row_idx % 2 == 1 else '#fcfcfc')
                weight = '600' if is_header else 'normal'
                table_html.append(f'<tr style="background-color: {bg};">')
                for cell in row:
                    tag = 'th' if is_header else 'td'
                    cell_formatted = format_inlines(cell.strip())
                    table_html.append(
                        f'<{tag} style="border: 1px solid #d0d7de; padding: 6px 10px; '
                        f'font-weight: {weight}; text-align: left; color: #1f2328;">{cell_formatted}</{tag}>'
                    )
                table_html.append('</tr>')
            table_html.append('</table>')
            output_html.append("\n".join(table_html))
            in_table = False
            table_rows = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Fenced code block: ```
        if line.strip().startswith("```"):
            close_all_lists()
            close_blockquote()
            close_table()
            if in_code_block:
                code_text = html.escape("\n".join(current_code_block))
                output_html.append(
                    f'<pre style="background-color: #f6f8fa; border: 1px solid #d0d7de; '
                    f'border-radius: 6px; padding: 10px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; '
                    f'font-size: 11px; line-height: 1.45; margin: 8px 0; color: #1f2328;">{code_text}</pre>'
                )
                current_code_block = []
                in_code_block = False
            else:
                in_code_block = True
                current_code_block = []
            i += 1
            continue

        if in_code_block:
            current_code_block.append(line)
            i += 1
            continue

        # Horizontal rules: ---, ***, ___
        if re.match(r'^\s*([-*_])(?:\s*\1){2,}\s*$', line):
            close_all_lists()
            close_blockquote()
            close_table()
            output_html.append('<hr style="height: 1px; border: none; background-color: #d0d7de; margin: 14px 0;" />')
            i += 1
            continue

        # Blockquote: > ...
        if line.strip().startswith(">"):
            close_all_lists()
            close_table()
            in_blockquote = True
            bq_text = re.sub(r'^\s*>\s?', '', line)
            blockquote_lines.append(format_inlines(bq_text))
            i += 1
            continue
        elif in_blockquote:
            close_blockquote()

        # Markdown tables: | ... |
        if "|" in line and (line.strip().startswith("|") or line.strip().endswith("|")):
            stripped = line.strip().strip("|")
            cells = stripped.split("|")
            if all(re.match(r'^\s*:?-+:?\s*$', c) for c in cells if c.strip()):
                i += 1
                continue
            close_all_lists()
            close_blockquote()
            in_table = True
            table_rows.append(cells)
            i += 1
            continue
        elif in_table:
            close_table()

        # Headings: #, ##, ###, ####, #####, ######
        m_heading = re.match(r'^(#{1,6})\s+(.*)$', line.strip())
        if m_heading:
            close_all_lists()
            close_blockquote()
            close_table()
            level = len(m_heading.group(1))
            heading_text = format_inlines(m_heading.group(2).strip())

            if level == 1:
                output_html.append(
                    f'<div style="font-size: 18px; font-weight: 600; color: #1f2328; '
                    f'margin-top: 14px; margin-bottom: 6px;">{heading_text}</div>'
                    f'<hr style="height: 1px; border: none; background-color: #d0d7de; margin: 2px 0 12px 0;" />'
                )
            elif level == 2:
                output_html.append(
                    f'<div style="font-size: 16px; font-weight: 600; color: #1f2328; '
                    f'margin-top: 12px; margin-bottom: 6px;">{heading_text}</div>'
                    f'<hr style="height: 1px; border: none; background-color: #d0d7de; margin: 2px 0 12px 0;" />'
                )
            elif level == 3:
                output_html.append(
                    f'<div style="font-size: 14px; font-weight: 600; color: #1f2328; '
                    f'margin-top: 12px; margin-bottom: 6px;">{heading_text}</div>'
                )
            else:
                output_html.append(
                    f'<div style="font-size: 13px; font-weight: 600; color: #1f2328; '
                    f'margin-top: 10px; margin-bottom: 4px;">{heading_text}</div>'
                )
            i += 1
            continue

        # Lists (unordered -/*/+ or ordered 1.)
        m_ul = re.match(r'^(\s*)([-*+])\s+(.*)$', line)
        m_ol = re.match(r'^(\s*)(\d+)\.\s+(.*)$', line)

        if m_ul or m_ol:
            close_blockquote()
            close_table()
            current_match = m_ul or m_ol
            raw_indent = current_match.group(1)
            indent_level = len(raw_indent.replace("\t", "    ")) // 2
            current_type = "ul" if m_ul else "ol"
            item_text = current_match.group(3)

            if not list_stack:
                list_stack.append((current_type, indent_level))
                output_html.append(f'<{current_type} style="margin-top: 4px; margin-bottom: 8px; padding-left: 18px;">')
            else:
                top_type, top_indent = list_stack[-1]
                if indent_level > top_indent:
                    list_stack.append((current_type, indent_level))
                    output_html.append(f'<{current_type} style="margin-top: 2px; margin-bottom: 4px; padding-left: 18px;">')
                elif indent_level < top_indent:
                    while list_stack and list_stack[-1][1] > indent_level:
                        ltype, _ = list_stack.pop()
                        output_html.append(f"</{ltype}>")
                    if not list_stack or list_stack[-1][0] != current_type:
                        list_stack.append((current_type, indent_level))
                        output_html.append(f'<{current_type} style="margin-top: 2px; margin-bottom: 4px; padding-left: 18px;">')

            task_box = ""
            if item_text.startswith("[ ] "):
                task_box = "☐ "
                item_text = item_text[4:]
            elif item_text.startswith("[x] ") or item_text.startswith("[X] "):
                task_box = "☑ "
                item_text = item_text[4:]

            formatted_item = format_inlines(item_text)
            output_html.append(
                f'<li style="margin-bottom: 6px; line-height: 1.5; color: #1f2328; font-size: 13px;">{task_box}{formatted_item}</li>'
            )
            i += 1
            continue
        elif list_stack:
            if line.startswith("   ") or line.startswith("\t"):
                formatted_cont = format_inlines(line.strip())
                output_html.append(f'<div style="margin-left: 18px; line-height: 1.5; color: #1f2328; font-size: 13px;">{formatted_cont}</div>')
                i += 1
                continue
            else:
                close_all_lists()

        # Blank line
        if not line.strip():
            close_all_lists()
            close_blockquote()
            close_table()
            i += 1
            continue

        # Regular paragraph
        close_all_lists()
        close_blockquote()
        close_table()
        p_text = format_inlines(line.strip())
        output_html.append(f'<p style="margin: 6px 0; line-height: 1.5; color: #1f2328; font-size: 13px;">{p_text}</p>')
        i += 1

    close_all_lists()
    close_blockquote()
    close_table()

    body_content = "\n".join(output_html)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif; font-size: 13px; color: #1f2328; background-color: #ffffff; margin: 10px;">
{body_content}
</body>
</html>"""
