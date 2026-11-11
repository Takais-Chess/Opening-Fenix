"""
book_export_service.py

Generates professional, printable chess repertoire textbooks (in HTML and PDF format)
styled after classic chess publications (e.g. Quality Chess Grandmaster Repertoire).
Features:
- Two-column continuous book layout with justified text and chapter headers.
- Ink-saver vector board diagrams with white margins, 0% ink light squares, and light slate dark squares.
- Faithful rendering of ChessBase/Chessable [%cal ...] arrows and [%csl ...] square highlights.
- Native language support (German 'de' with German piece letters K, D, T, L, S, 0-0 or English 'en').
- Automatic chapter splitting based on major opening systems.
- Direct PDF export via headless Chromium (Microsoft Edge / Google Chrome) or HTML browser export.
"""

import os
import sys
import re
import math
import json
import base64
import sqlite3
import subprocess
import shutil
import tempfile
import uuid
import pathlib
from typing import Optional, Callable, Dict, List, Tuple, Any

import chess
import chess.svg

from opening_fenix.core.utils import parse_chessbase_annotations, parse_comment, localize_san, parse_variation_name
from opening_fenix.core.logger import logger

# ─── TINTENSPAR-PALETTE (Minimal Ink Consumption) ───────────────────────────

INK_SAVER_COLORS = {
    'margin': '#ffffff',             # Pure white border (removes heavy black blocks)
    'inner border': '#475569',       # Crisp thin slate border
    'outer border': '#475569',
    'square light': '#ffffff',       # 0% ink
    'square dark': '#e8edf2',        # Very light slate tint
    'square light lastmove': '#ffffff',
    'square dark lastmove': '#cbd5e1',
    'coord': '#334155',              # Dark grey coordinates on white border
    'arrow green': 'rgba(22, 163, 74, 0.85)',
    'arrow red': 'rgba(220, 38, 38, 0.85)',
    'arrow yellow': 'rgba(202, 138, 4, 0.85)',
    'arrow blue': 'rgba(37, 99, 235, 0.85)',
}

COLOR_MAP = {
    'green': 'rgba(22, 163, 74, 0.85)',
    'red': 'rgba(220, 38, 38, 0.85)',
    'blue': 'rgba(37, 99, 235, 0.85)',
    'yellow': 'rgba(202, 138, 4, 0.85)'
}

FILL_MAP = {
    'green': 'rgba(34, 197, 94, 0.28)',
    'red': 'rgba(239, 68, 68, 0.28)',
    'blue': 'rgba(59, 130, 246, 0.28)',
    'yellow': 'rgba(234, 179, 8, 0.28)'
}

OPENING_NAMES_DE = {
    "Ruy Lopez": "Spanische Partie (Ruy Lopez)",
    "Italian": "Italienische Partie & Zweispringerspiel",
    "Scotch": "Schottische Partie",
    "Four Knights": "Vierspringerspiel",
    "The Vienna": "Wiener Partie",
    "King's Gambit": "Königsgambit",
    "Ponziani": "Ponziani-Eröffnung",
    "Bishop's Opening": "Läuferspiel",
    "Center Game": "Mittelspiel & Mittelgambit",
    "Sicilian": "Sizilianische Verteidigung",
    "French": "Französische Verteidigung",
    "Caro-Kann": "Caro-Kann-Verteidigung",
    "Scandinavian": "Skandinavische Verteidigung",
    "Alekhine": "Aljechin-Verteidigung",
    "Pirc": "Pirc-Ufimzew-Verteidigung",
    "Modern": "Moderne Verteidigung",
    "3.Nc3": "Vierspringerspiel (3.Sc3)",
    "2.d4": "Mittelspiel & Mittelgambit (2.d4)",
    "2.Bc4": "Läuferspiel (2.Lc4)",
    "2.f4": "Königsgambit (2.f4)",
    "2.Nc3": "Wiener Partie (2.Sc3)"
}


def find_headless_browser() -> Optional[str]:
    """Finds installed Microsoft Edge or Google Chrome executable on Windows."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    
    # Try which / PATH
    for name in ["msedge.exe", "msedge", "chrome.exe", "chrome"]:
        p = shutil.which(name)
        if p and os.path.isfile(p):
            return p
            
    return None


def _run_chromium_pdf(browser_path: str, html_path: str, output_pdf_path: str, timeout: int = 240) -> subprocess.CompletedProcess:
    """
    Executes Chromium headless to print HTML to PDF, isolated with its own temporary user data directory.
    Uses forward-slash paths for Windows Chromium CLI compatibility and multi-strategy fallbacks
    (--headless=new, --headless=old, --headless) to guarantee generation on any Chromium version.
    """
    file_uri = pathlib.Path(html_path).resolve().as_uri()
    user_data_dir = tempfile.mkdtemp(prefix="fenix_edge_")
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    temp_render_pdf = os.path.join(tempfile.gettempdir(), f"fenix_render_{uuid.uuid4().hex}.pdf")
    temp_render_pdf_arg = temp_render_pdf.replace("\\", "/")
    user_data_dir_arg = user_data_dir.replace("\\", "/")

    extra_flags = [
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-pdf-header-footer",
        "--js-flags=--max-old-space-size=8192",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-default-apps",
        "--mute-audio",
    ]
    strategies = [
        [browser_path, "--headless=new", "--run-all-compositor-stages-before-draw"] + extra_flags + [f"--user-data-dir={user_data_dir_arg}", f"--print-to-pdf={temp_render_pdf_arg}", file_uri],
        [browser_path, "--headless=old"] + extra_flags + [f"--user-data-dir={user_data_dir_arg}", f"--print-to-pdf={temp_render_pdf_arg}", file_uri],
        [browser_path, "--headless"] + extra_flags + [f"--user-data-dir={user_data_dir_arg}", f"--print-to-pdf={temp_render_pdf_arg}", file_uri]
    ]

    last_res = None
    # Build a clean environment for Chromium without PyInstaller (_PYI_*), Qt, or Windows
    # Program Compatibility Assistant (__COMPAT_LAYER=DetectorsAppHealth) variables.
    # When Opening Fenix.exe is launched from the installer or with PCA shims active,
    # inherited __COMPAT_LAYER causes msedge.exe/chrome.exe to immediately exit with code 0
    # without generating the PDF.
    clean_env = {}
    for k, v in os.environ.items():
        ku = k.upper()
        if ku in ("__COMPAT_LAYER", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH") or ku.startswith("_PYI_") or ku.startswith("QT_"):
            continue
        if ku == "PATH":
            parts = [p for p in v.split(os.pathsep) if "_internal" not in p.lower() and "pyqt6" not in p.lower()]
            clean_env[k] = os.pathsep.join(parts)
        else:
            clean_env[k] = v

    try:
        for cmd in strategies:
            try:
                res = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=timeout,
                    creationflags=creationflags,
                    env=clean_env,
                    cwd=tempfile.gettempdir(),
                    stdin=subprocess.DEVNULL,
                )
                last_res = res
                if os.path.isfile(temp_render_pdf) and os.path.getsize(temp_render_pdf) > 0:
                    break
            except Exception as e:
                logger.warning(f"Chromium headless strategy failed: {e}")

        if os.path.isfile(temp_render_pdf) and os.path.getsize(temp_render_pdf) > 0:
            dest_dir = os.path.dirname(os.path.abspath(output_pdf_path))
            os.makedirs(dest_dir, exist_ok=True)
            if os.path.exists(output_pdf_path):
                try:
                    os.remove(output_pdf_path)
                except Exception:
                    pass
            shutil.move(temp_render_pdf, output_pdf_path)
        else:
            err_det = (last_res.stderr or last_res.stdout).decode("utf-8", errors="replace").strip() if last_res else "Keine Ausgabe"
            logger.error(f"Chromium PDF generation failed after trying all strategies. Exit-Code: {last_res.returncode if last_res else 'None'}, Details: {err_det}")

        return last_res
    finally:
        if os.path.isfile(temp_render_pdf):
            try:
                os.remove(temp_render_pdf)
            except Exception:
                pass
        if os.path.isdir(user_data_dir):
            try:
                shutil.rmtree(user_data_dir, ignore_errors=True)
            except Exception:
                pass


def extract_variation_name(
    v1: Optional[str] = None,
    v2: Optional[str] = None,
    v3: Optional[str] = None,
    exclude_title: Optional[str] = None,
    language: str = "de"
) -> Optional[str]:
    """Extracts variation name from variation_2, variation_3, or variation_1 in the requested language."""
    names = []
    ex = parse_variation_name(str(exclude_title).strip(), lang=language, default_lang="de" if language == "de" else "en").strip().lower() if exclude_title else ""
    for v in [v2, v3, v1]:
        if v and str(v).strip():
            c = parse_variation_name(str(v).strip(), lang=language, default_lang="de" if language == "de" else "en").strip()
            if c and c.lower() != ex and c not in names:
                names.append(c)
    return " · ".join(names) if names else None


def format_san(san: str, language: str = "de") -> str:
    """Formats SAN for German notation if requested."""
    if not san:
        return ""
    if language == "de":
        loc = localize_san(san, "de")
        # Format Castling in German book style (0-0 / 0-0-0)
        loc = loc.replace("O-O-O", "0-0-0").replace("O-O", "0-0")
        return loc
    return san


# ─── SHARED SVG DEFINITIONS (90% Size & Memory Reduction for Large Books) ───

def _build_shared_svg_defs() -> str:
    all_pieces_board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -")
    sample_svg = chess.svg.board(all_pieces_board, orientation=chess.WHITE, size=195, coordinates=True, colors=INK_SAVER_COLORS)
    defs_match = re.search(r"<defs>(.*?)</defs>", sample_svg, flags=re.DOTALL)
    piece_defs_inner = defs_match.group(1) if defs_match else ""

    empty_board = chess.Board(None)
    empty_w = chess.svg.board(empty_board, orientation=chess.WHITE, size=195, coordinates=True, colors=INK_SAVER_COLORS)
    empty_b = chess.svg.board(empty_board, orientation=chess.BLACK, size=195, coordinates=True, colors=INK_SAVER_COLORS)

    def _extract_bg(svg_str: str) -> str:
        inner = re.sub(r"^<svg[^>]*>|</svg>$", "", svg_str)
        inner = re.sub(r"<desc>.*?</desc>", "", inner, flags=re.DOTALL)
        inner = re.sub(r"<defs>.*?</defs>", "", inner, flags=re.DOTALL)
        return inner

    bg_w = _extract_bg(empty_w)
    bg_b = _extract_bg(empty_b)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'style="position:absolute;width:0;height:0;overflow:hidden;" aria-hidden="true">'
        f'<defs>{piece_defs_inner}'
        f'<g id="fenix-board-w">{bg_w}</g>'
        f'<g id="fenix-board-b">{bg_b}</g>'
        '</defs></svg>'
    )


SHARED_SVG_DEFS = _build_shared_svg_defs()

PIECE_ID_MAP = {
    (chess.PAWN, chess.WHITE): "white-pawn",
    (chess.KNIGHT, chess.WHITE): "white-knight",
    (chess.BISHOP, chess.WHITE): "white-bishop",
    (chess.ROOK, chess.WHITE): "white-rook",
    (chess.QUEEN, chess.WHITE): "white-queen",
    (chess.KING, chess.WHITE): "white-king",
    (chess.PAWN, chess.BLACK): "black-pawn",
    (chess.KNIGHT, chess.BLACK): "black-knight",
    (chess.BISHOP, chess.BLACK): "black-bishop",
    (chess.ROOK, chess.BLACK): "black-rook",
    (chess.QUEEN, chess.BLACK): "black-queen",
    (chess.KING, chess.BLACK): "black-king",
}


def render_board_svg(
    fen: str,
    parsed_annotations: dict,
    color: str = 'b',
    caption: str = "",
    size: int = 195
) -> str:
    """Renders a compact, ink-saver vector SVG board diagram referencing SHARED_SVG_DEFS."""
    try:
        board = chess.Board(fen)
    except Exception:
        board = chess.Board()

    orientation = chess.BLACK if color.lower() == 'b' else chess.WHITE
    bg_id = "fenix-board-w" if orientation == chess.WHITE else "fenix-board-b"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 390 390" width="{size}" height="{size}">',
        f'<use href="#{bg_id}" xlink:href="#{bg_id}" fill="#ffffff" />',
    ]

    # Square Highlights
    for item in parsed_annotations.get("highlights", []):
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            sq, col = item[0], item[1]
        else:
            sq, col = item, 'red'
        col_hex = FILL_MAP.get(col, FILL_MAP['red'])
        file_idx = chess.square_file(sq)
        rank_idx = chess.square_rank(sq)
        x = 15 + (file_idx if orientation == chess.WHITE else 7 - file_idx) * 45
        y = 15 + (7 - rank_idx if orientation == chess.WHITE else rank_idx) * 45
        parts.append(f'<rect x="{x}" y="{y}" width="45" height="45" fill="{col_hex}" stroke="none" />')

    # Pieces
    for sq, piece in board.piece_map().items():
        file_idx = chess.square_file(sq)
        rank_idx = chess.square_rank(sq)
        x = 15 + (file_idx if orientation == chess.WHITE else 7 - file_idx) * 45
        y = 15 + (7 - rank_idx if orientation == chess.WHITE else rank_idx) * 45
        pid = PIECE_ID_MAP[(piece.piece_type, piece.color)]
        parts.append(f'<use href="#{pid}" xlink:href="#{pid}" transform="translate({x}, {y})" />')

    # Arrows & Circles
    board_offset = 15.0
    square_size = 45.0
    for tail, head, col in parsed_annotations.get("arrows", []):
        color_val = COLOR_MAP.get(col, COLOR_MAP['green'])
        opacity_attr = ""
        if len(color_val) == 9 and color_val.startswith("#"):
            alpha = int(color_val[7:9], 16) / 255.0
            color_val = color_val[:7]
            opacity_attr = f' opacity="{alpha:.2f}"'
        tail_file = chess.square_file(tail)
        tail_rank = chess.square_rank(tail)
        head_file = chess.square_file(head)
        head_rank = chess.square_rank(head)
        xtail = board_offset + (tail_file + 0.5 if orientation == chess.WHITE else 7.5 - tail_file) * square_size
        ytail = board_offset + (7.5 - tail_rank if orientation == chess.WHITE else tail_rank + 0.5) * square_size
        xhead = board_offset + (head_file + 0.5 if orientation == chess.WHITE else 7.5 - head_file) * square_size
        yhead = board_offset + (7.5 - head_rank if orientation == chess.WHITE else head_rank + 0.5) * square_size
        if (head_file, head_rank) == (tail_file, tail_rank):
            parts.append(
                f'<circle cx="{xhead}" cy="{yhead}" r="{square_size * 0.9 / 2}" stroke-width="{square_size * 0.1}" stroke="{color_val}"{opacity_attr} fill="none" class="circle" />'
            )
        else:
            marker_size = 0.75 * square_size
            marker_margin = 0.1 * square_size
            dx, dy = xhead - xtail, yhead - ytail
            hypot = math.hypot(dx, dy)
            shaft_x = xhead - dx * (marker_size + marker_margin) / hypot
            shaft_y = yhead - dy * (marker_size + marker_margin) / hypot
            xtip = xhead - dx * marker_margin / hypot
            ytip = yhead - dy * marker_margin / hypot
            p1x, p1y = xtip, ytip
            p2x = shaft_x + dy * 0.5 * marker_size / hypot
            p2y = shaft_y - dx * 0.5 * marker_size / hypot
            p3x = shaft_x - dy * 0.5 * marker_size / hypot
            p3y = shaft_y + dx * 0.5 * marker_size / hypot
            parts.append(
                f'<line x1="{xtail}" y1="{ytail}" x2="{shaft_x}" y2="{shaft_y}" stroke="{color_val}"{opacity_attr} stroke-width="{square_size * 0.2}" stroke-linecap="butt" class="arrow" />'
            )
            parts.append(
                f'<polygon points="{p1x},{p1y} {p2x},{p2y} {p3x},{p3y}" fill="{color_val}"{opacity_attr} class="arrow" />'
            )

    parts.append("</svg>")
    svg_code = "".join(parts)

    caption_html = f"<div class='diagram-caption'>{caption}</div>" if caption else ""
    return f"""
    <div class="column-diagram">
        {svg_code}
        {caption_html}
    </div>
    """


def extract_clean_comment(raw: Optional[str], language: str = "de") -> Tuple[str, dict]:
    """
    Extracts text in target language and returns (clean_text, parsed_annotations).
    Strictly adheres to language choice (de, en, or all) without cross-language fallback:
    - 'de': only German comments
    - 'en': only English comments
    - 'all': all available languages ([DE] ... [EN] ...)
    """
    if not raw or not raw.strip():
        return "", {"arrows": [], "highlights": []}

    raw = raw.strip()
    # Uses Opening-Fenix's central parse_comment which respects exact language
    target_text = parse_comment(raw, lang=language, default_lang="de" if language == "de" else "en")

    parsed_all = parse_chessbase_annotations(raw)
    parsed_target = parse_chessbase_annotations(target_text) if target_text else {"clean_text": "", "arrows": [], "highlights": []}

    clean_text = parsed_target.get("clean_text") or ""
    arrows = parsed_target.get("arrows") or parsed_all.get("arrows", [])
    highlights = parsed_target.get("highlights") or parsed_all.get("highlights", [])

    return clean_text, {"arrows": arrows, "highlights": highlights}


def append_move_to_path(path: str, m_num: int, white_turn: bool, loc_san: str) -> str:
    """Helper to format SAN paths smoothly with move numbers."""
    if not path:
        return f"{m_num}.{loc_san}" if white_turn else f"{m_num}...{loc_san}"
    if white_turn:
        return f"{path} {m_num}.{loc_san}".strip()
    else:
        last_tokens = path.split()
        if last_tokens and any(t.startswith(f"{m_num}.") for t in last_tokens[-2:]):
            return f"{path} {loc_san}".strip()
        else:
            return f"{path} {m_num}...{loc_san}".strip()


def get_course_icon_data_uri(db_path: Optional[str] = None, repo_name: str = "") -> Optional[str]:
    """
    Finds the course cover image (cover.png, cover.jpg, etc.) for the repertoire and returns it as a base64 data URI.
    """
    candidates = []
    if db_path:
        db_dir = os.path.dirname(os.path.abspath(db_path))
        for ext in ("png", "jpg", "jpeg", "svg"):
            candidates.append(os.path.join(db_dir, f"cover.{ext}"))
            candidates.append(os.path.join(db_dir, f"icon.{ext}"))
    if repo_name:
        try:
            from opening_fenix.creator.repo_selection_dialog import get_repertoire_cover_path
            cp = get_repertoire_cover_path(repo_name)
            if cp:
                candidates.append(cp)
        except Exception:
            pass

    for path in candidates:
        if path and os.path.isfile(path):
            try:
                ext = os.path.splitext(path)[1].lower().lstrip(".")
                mime = "image/png" if ext == "png" else "image/jpeg" if ext in ("jpg", "jpeg") else "image/svg+xml" if ext == "svg" else "image/png"
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                return f"data:{mime};base64,{b64}"
            except Exception as e:
                logger.warning(f"Failed to encode course cover '{path}': {e}")
    return None


def build_book_html(
    metadata: dict,
    chapters: List[dict],
    language: str = "de",
    variation_index_html: str = "",
    variation_count: int = 0,
    page_map: Optional[Dict[Any, int]] = None
) -> str:
    """Generates the full HTML markup for the Quality Chess style repertoire textbook."""
    repo_name = metadata.get("name", "Repertoire")
    repo_color = metadata.get("color", "b")
    level_name = metadata.get("level_name", "Grundlagen")
    color_label = "Schwarz" if repo_color.lower() == 'b' else "Weiß"
    if language == "en":
        color_label = "Black" if repo_color.lower() == 'b' else "White"

    title_text = f"{repo_name} — Lehrbuch" if language == "de" else f"{repo_name} — Textbook"
    sub_text = f"Repertoire für {color_label} • {level_name}" if language == "de" else f"Repertoire for {color_label} • {level_name}"
    created_with_text = "Erstellt mit Opening-Fenix" if language == "de" else "Created with Opening-Fenix"
    toc_heading = "Inhaltsverzeichnis" if language == "de" else "Table of Contents"

    course_icon_uri = metadata.get("course_icon_data_uri") or metadata.get("cover_data_uri")
    if course_icon_uri:
        icon_html = f"""<div class="cover-icon-wrap"><img class="cover-icon" src="{course_icon_uri}" alt="" /></div>"""
    else:
        icon_html = """<div class="cover-icon-wrap cover-icon-placeholder"><span>♟</span></div>"""

    # Table of contents items
    toc_items_html = []
    for idx, chap in enumerate(chapters, start=1):
        c_title = parse_variation_name(chap["title"], lang=language, default_lang="de" if language == "de" else "en")
        prefix = chap.get("san_prefix", "")
        m_cnt = chap.get("move_count", 0)
        moves_info = f"({m_cnt} Züge)" if language == "de" else f"({m_cnt} moves)"
        p_info = ""
        dots_html = ""
        if page_map and idx in page_map:
            p_label = f"S. {page_map[idx]}" if language == "de" else f"p. {page_map[idx]}"
            dots_html = '<span class="toc-dots"></span>'
            p_info = f'<span class="toc-page">{p_label}</span>'

        subvar_html = ""
        if chap.get("subvars"):
            subvar_list = " · ".join(
                parse_variation_name(sv, lang=language, default_lang="de" if language == "de" else "en")
                for sv in chap["subvars"][:6]
                if sv
            )
            subvar_html = f'<div class="toc-subvar-row"><span class="toc-subvar-icon">↳</span> <span class="toc-subvar-text">{subvar_list}</span></div>'

        toc_items_html.append(f"""
        <div class="toc-row">
            <span class="toc-title"><a href="#chapter-{idx}">Kapitel {idx}: {c_title}</a></span>
            <span class="toc-sub">{prefix} {moves_info}</span>
            {dots_html}
            {p_info}
        </div>
        {subvar_html}
        """)

    if variation_index_html:
        idx_title = "Varianten-Index" if language == "de" else "Index of Variations"
        vars_info = f"({variation_count} Varianten)" if language == "de" else f"({variation_count} variations)"
        idx_dots = ""
        idx_p_info = ""
        if page_map and "index" in page_map:
            p_label = f"S. {page_map['index']}" if language == "de" else f"p. {page_map['index']}"
            idx_dots = '<span class="toc-dots"></span>'
            idx_p_info = f'<span class="toc-page">{p_label}</span>'

        toc_items_html.append(f"""
        <div class="toc-row toc-index-row">
            <span class="toc-title"><a href="#variation-index">{idx_title}</a></span>
            <span class="toc-sub">{vars_info}</span>
            {idx_dots}
            {idx_p_info}
        </div>
        """)

    # Dynamic page header rules for each chapter and index
    chapter_page_rules_list = []
    toc_label = "Inhaltsverzeichnis" if language == "de" else "Table of Contents"
    idx_label = "Varianten-Index" if language == "de" else "Variation Index"
    chapter_page_rules_list.append(f"""
        @page toc-page {{
            @top-left {{
                content: "{repo_name} · {toc_label}";
            }}
        }}
        .toc-section {{
            page: toc-page;
        }}
        @page var-index {{
            @top-left {{
                content: "{repo_name} · {idx_label}";
            }}
        }}
        .index-section {{
            page: var-index;
        }}
    """)

    # Build chapters HTML
    chapters_html = []
    for idx, chap in enumerate(chapters, start=1):
        c_title = parse_variation_name(chap["title"], lang=language, default_lang="de" if language == "de" else "en")
        clean_c_title = c_title.replace('"', '\\"')
        chapter_page_rules_list.append(f"""
        @page chapter-{idx} {{
            @top-left {{
                content: "{repo_name} · {clean_c_title}";
            }}
        }}
        #chapter-{idx} {{
            page: chapter-{idx};
        }}
        """)

        prefix = chap.get("san_prefix", "")
        content_html = chap.get("content_html", "")

        chap_block = f"""
        <div class="chapter-container" id="chapter-{idx}">
            <div class="chapter-header">
                <div class="chapter-tag">Kapitel {idx}</div>
                <h2 class="chapter-title">{c_title}</h2>
                <div class="chapter-prefix">{prefix}</div>
            </div>
            <div class="two-columns">
                {content_html}
            </div>
        </div>
        """
        chapters_html.append(chap_block)

    chapter_page_rules = "\n".join(chapter_page_rules_list)
    full_html = f"""<!DOCTYPE html>
<html lang="{language}">
<head>
    <meta charset="UTF-8">
    <title>{title_text}</title>
    <style>
        @page {{
            size: A4 portrait;
            margin: 15mm 16mm 16mm 16mm;
            @top-left {{
                content: "{repo_name} · {level_name}";
                font-family: Georgia, "Times New Roman", serif;
                font-size: 8pt;
                font-style: italic;
                color: #64748b;
            }}
            @top-right {{
                content: counter(page);
                font-family: Georgia, "Times New Roman", serif;
                font-size: 8.5pt;
                font-weight: bold;
                color: #0f172a;
            }}
            @bottom-center {{
                content: "";
                border-top: 0.5pt solid #cbd5e1;
            }}
        }}

        @page:first {{
            @top-left {{ content: ""; }}
            @top-right {{ content: ""; }}
            @bottom-center {{ content: ""; border: none; }}
        }}

        @page toc-page:first {{
            @top-left {{ content: ""; }}
            @top-right {{ content: ""; }}
            @bottom-center {{ content: ""; border: none; }}
        }}

        {chapter_page_rules}

        @media print {{
            body {{
                background: #ffffff !important;
                padding: 0 !important;
                margin: 0 !important;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}
            .book-wrapper {{
                max-width: 100% !important;
                padding: 0 !important;
                box-shadow: none !important;
            }}
            .chapter-container {{
                page-break-before: always;
            }}
            .chapter-container:first-of-type {{
                page-break-before: auto;
            }}
            .column-diagram, .variation-heading, .diagram-comment-group {{
                break-inside: avoid;
                page-break-inside: avoid;
            }}
        }}

        body {{
            font-family: Georgia, Cambria, "Times New Roman", Times, serif;
            font-size: 9.5pt;
            line-height: 1.36;
            color: #111827;
            background: #f1f5f9;
            margin: 0;
            padding: 24px;
        }}

        .book-wrapper {{
            max-width: 840px;
            margin: 0 auto;
            background: #ffffff;
            padding: 28px 36px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.08);
            box-sizing: border-box;
        }}

        /* Cover Header (combined with Table of Contents on first page) */
        .cover-header {{
            display: flex;
            align-items: center;
            gap: 20px;
            padding: 0 0 16px 0;
            border-bottom: 2pt solid #0f172a;
            margin-bottom: 20px;
        }}
        .cover-icon-wrap {{
            flex-shrink: 0;
            width: 72px;
            height: 72px;
        }}
        .cover-icon {{
            width: 72px;
            height: 72px;
            border-radius: 8px;
            object-fit: cover;
            box-shadow: 0 2px 5px rgba(15, 23, 42, 0.12);
            border: 1px solid #cbd5e1;
            display: block;
        }}
        .cover-icon-placeholder {{
            width: 72px;
            height: 72px;
            border-radius: 8px;
            background: linear-gradient(135deg, rgba(211, 84, 0, 0.18), rgba(211, 84, 0, 0.05));
            border: 1px dashed rgba(211, 84, 0, 0.35);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 36px;
            color: #d35400;
        }}
        .cover-text {{
            flex: 1;
            min-width: 0;
        }}
        .cover-title {{
            font-size: 22pt;
            font-weight: bold;
            color: #0f172a;
            margin: 0 0 4px 0;
            letter-spacing: -0.02em;
            line-height: 1.15;
        }}
        .cover-subtitle {{
            font-size: 11pt;
            color: #475569;
            margin: 0 0 3px 0;
        }}
        .cover-meta {{
            font-size: 8.5pt;
            color: #94a3b8;
        }}

        /* Table of Contents */
        .toc-section {{
            margin-bottom: 30px;
            page-break-after: always;
        }}
        .toc-heading {{
            font-size: 15pt;
            font-weight: bold;
            border-bottom: 1.5pt solid #0f172a;
            padding-bottom: 4px;
            margin-bottom: 14px;
        }}
        .toc-row {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 6px 0;
            border-bottom: 0.5pt solid #f1f5f9;
            font-size: 10pt;
        }}
        .toc-title a {{
            text-decoration: none;
            color: #0f172a;
            font-weight: bold;
        }}
        .toc-title a:hover {{
            color: #0284c7;
        }}
        .toc-sub {{
            font-size: 8.5pt;
            color: #64748b;
        }}

        /* Chapter Layout */
        .chapter-container {{
            margin-bottom: 35px;
        }}
        .chapter-header {{
            border-bottom: 1.5pt solid #0f172a;
            padding-bottom: 4px;
            margin-bottom: 14px;
        }}
        .chapter-tag {{
            font-size: 8.5pt;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #0284c7;
            margin-bottom: 2px;
        }}
        .chapter-title {{
            font-size: 16pt;
            font-weight: bold;
            color: #0f172a;
            margin: 0 0 4px 0;
        }}
        .chapter-prefix {{
            font-size: 9pt;
            color: #475569;
            font-style: italic;
        }}

        /* Two Continuous Columns */
        .two-columns {{
            column-count: 2;
            column-gap: 22px;
            column-rule: 0.5pt solid #e2e8f0;
            text-align: justify;
            text-justify: inter-word;
        }}

        .moves {{
            font-weight: bold;
            color: #000000;
        }}

        p {{
            margin: 0 0 7px 0;
            text-indent: 0;
        }}

        .variation-heading {{
            font-weight: bold;
            margin-top: 12px;
            margin-bottom: 5px;
            break-inside: avoid;
            page-break-inside: avoid;
            break-after: avoid;
            page-break-after: avoid;
        }}

        .variation-name {{
            font-style: italic;
            font-weight: 600;
            color: #334155;
            margin-left: 4px;
        }}

        .mainline-variation-heading {{
            margin-top: 13px;
            margin-bottom: 6px;
            break-inside: avoid;
            page-break-inside: avoid;
            break-after: avoid;
            page-break-after: avoid;
        }}

        .subvar-badge {{
            font-size: 7.5pt;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-weight: 700;
            color: #475569;
            background: #f1f5f9;
            padding: 2px 6px;
            border-radius: 3px;
            border: 1px solid #cbd5e1;
            margin-right: 6px;
            vertical-align: middle;
        }}

        .subvar-title {{
            font-size: 10pt;
            font-weight: bold;
            font-style: italic;
            color: #1e293b;
            vertical-align: middle;
        }}

        .toc-subvar-row {{
            font-size: 8.5pt;
            color: #475569;
            padding-left: 20px;
            margin-top: -3px;
            margin-bottom: 7px;
            font-style: italic;
        }}

        .toc-subvar-icon {{
            color: #94a3b8;
            margin-right: 4px;
            font-style: normal;
        }}

        .index-varname {{
            font-size: 8pt;
            font-style: italic;
            font-weight: normal;
            color: #475569;
            margin-left: 4px;
        }}

        .diagram-comment-group {{
            break-inside: avoid;
            page-break-inside: avoid;
            margin-bottom: 6px;
        }}

        .sideline-tag {{
            font-weight: bold;
            font-size: 10pt;
            color: #0369a1;
        }}

        /* Column Diagram */
        .column-diagram {{
            margin: 8px auto 9px auto;
            text-align: center;
            width: 195px;
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .column-diagram svg {{
            width: 195px;
            height: 195px;
            display: block;
            border-radius: 2px;
        }}
        .diagram-caption {{
            font-size: 7.5pt;
            font-style: italic;
            color: #475569;
            margin-top: 3px;
            text-align: center;
        }}

        ul.book-list {{
            margin: 3px 0 7px 16px;
            padding: 0;
            font-size: 9pt;
        }}
        ul.book-list li {{
            margin-bottom: 2px;
        }}

        .transposition-note {{
            font-size: 8.5pt;
            font-style: italic;
            color: #475569;
            margin: 3px 0 8px 8px;
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .transposition-note a {{
            color: #0f172a;
            font-weight: 500;
            text-decoration: none;
            border-bottom: 0.5pt dotted #94a3b8;
        }}
        .transposition-note a:hover {{
            color: #0284c7;
            border-bottom-style: solid;
        }}

        .transposition-inline {{
            font-weight: normal;
            font-size: 8.5pt;
            font-style: italic;
            color: #475569;
            margin-left: 6px;
            white-space: nowrap;
        }}
        .transposition-inline a {{
            color: #0f172a;
            font-weight: 500;
            text-decoration: none;
            border-bottom: 0.5pt dotted #94a3b8;
        }}
        .transposition-inline a:hover {{
            color: #0284c7;
            border-bottom-style: solid;
        }}

        /* Varianten-Index */
        .index-section {{
            margin-top: 35px;
            padding-top: 20px;
            border-top: 2pt solid #0f172a;
            page-break-before: always;
        }}
        .index-header {{
            margin-bottom: 16px;
            border-bottom: 1.5pt solid #0f172a;
            padding-bottom: 6px;
        }}
        .index-title {{
            font-size: 18pt;
            font-weight: bold;
            color: #0f172a;
            margin: 0 0 4px 0;
        }}
        .index-sub {{
            font-size: 9pt;
            color: #64748b;
            font-style: italic;
        }}
        .index-tree-box {{
            font-family: Consolas, "Liberation Mono", Menlo, Courier, monospace;
            font-size: 8.5pt;
            line-height: 1.45;
            background: transparent;
            padding: 4px 0;
            border: none;
        }}
        .index-row {{
            display: flex;
            align-items: baseline;
            margin-bottom: 2.5px;
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .index-branch {{
            display: inline-flex;
            align-items: baseline;
            white-space: nowrap;
            word-break: normal;
            overflow-wrap: normal;
        }}
        .index-moves {{
            font-weight: bold;
            color: #0f172a;
            white-space: nowrap;
        }}
        .index-prefix {{
            color: #94a3b8;
            user-select: none;
            white-space: pre;
            font-weight: normal;
        }}
        .index-moves {{
            font-weight: bold;
            color: #0f172a;
        }}
        .index-trans {{
            font-style: italic;
            color: #475569;
            font-weight: normal;
            font-size: 8pt;
            margin-left: 4px;
        }}
        .index-page {{
            font-size: 8.5pt;
            color: #475569;
            margin-left: 4px;
            font-style: normal;
            font-weight: normal;
        }}
        .toc-dots {{
            flex-grow: 1;
            border-bottom: 1px dotted #cbd5e1;
            margin: 0 10px 3px 10px;
            height: 0;
        }}
        .toc-page {{
            font-size: 9.5pt;
            color: #334155;
            font-weight: bold;
            white-space: nowrap;
        }}
        .index-dots {{
            flex-grow: 1;
            border-bottom: 1px dotted #cbd5e1;
            margin: 0 8px 3px 8px;
            min-width: 15px;
            height: 0;
        }}
        .index-target {{
            white-space: nowrap;
        }}
        .index-chap-link {{
            font-family: Georgia, serif;
            font-size: 8.5pt;
            font-weight: bold;
            color: #0369a1;
            text-decoration: none;
            white-space: nowrap;
        }}
        .index-chap-link:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
{SHARED_SVG_DEFS}

<div class="book-wrapper">

    <!-- Inhaltsverzeichnis mit Titel & Kurs-Icon auf Seite 1 -->
    <div class="toc-section">
        <div class="cover-header">
            {icon_html}
            <div class="cover-text">
                <h1 class="cover-title">{repo_name}</h1>
                <div class="cover-subtitle">{sub_text}</div>
                <div class="cover-meta">{created_with_text}</div>
            </div>
        </div>
        <div class="toc-heading">{toc_heading}</div>
        {"".join(toc_items_html)}
    </div>

    <!-- Kapitel -->
    {"".join(chapters_html)}

    <!-- Varianten-Index -->
    {variation_index_html}

</div>

</body>
</html>
"""
    return full_html


def flatten_subtree(
    conn: sqlite3.Connection,
    start_pos_id: int,
    start_move_num: int,
    is_white_turn: bool,
    color: str = 'b',
    level: Optional[int] = None,
    language: str = "de",
    visited_positions: Optional[Dict[int, dict]] = None,
    chap_idx: int = 1,
    chap_title: str = "",
    chap_prefix: str = "",
    page_map: Optional[Dict[Any, int]] = None
) -> str:
    """
    Recursively flattens a subtree into Quality Chess style HTML paragraphs,
    sidelines, comments, and column diagrams. Consecutive moves without comments
    flow together in a single continuous line (e.g. 12.Lxf6 Sxf6 13.Dh4 Ke7).
    Detects transpositions and replaces duplicated subtrees with informative cross-references.
    """
    cur = conn.cursor()
    lvl_filter = f"AND rm.level <= {level}" if level is not None else ""
    if visited_positions is None:
        visited_positions = {}

    pos_cols = {r[1] for r in cur.execute("PRAGMA table_info(positions)").fetchall()}
    v1_expr = "p.variation_1" if "variation_1" in pos_cols else "NULL"
    v2_expr = "p.variation_2" if "variation_2" in pos_cols else "NULL"
    v3_expr = "p.variation_3" if "variation_3" in pos_cols else "NULL"

    def get_children(p_id):
        cur.execute(f"""
            SELECT m.id, m.san, m.to_position_id, p.fen, p.comment, {v1_expr}, {v2_expr}, {v3_expr}
            FROM repertoire_moves rm
            JOIN moves m ON rm.move_id = m.id
            JOIN positions p ON m.to_position_id = p.id
            WHERE m.from_position_id = ? AND rm.is_active = 1 {lvl_filter}
            ORDER BY m.priority_score DESC
        """, (p_id,))
        return cur.fetchall()

    html_blocks = []
    diag_tracker = {"plies_since_diagram": 0}

    # 1. Kapitel-Startstellung (Tabia des Kapitels)
    cur.execute("SELECT fen, comment FROM positions WHERE id = ?", (start_pos_id,))
    start_row = cur.fetchone()
    if start_row and start_row[0]:
        start_fen, start_raw_c = start_row
        st_clean, st_anno = extract_clean_comment(start_raw_c, language)
        start_cap = "Ausgangsstellung des Kapitels" if language == "de" else "Chapter Starting Position"
        start_diag = render_board_svg(start_fen, st_anno, color=color, caption=start_cap, size=195)
        start_comments = "".join(f"<p>{l.strip()}</p>\n" for l in st_clean.split("\n") if l.strip()) if st_clean else ""
        if start_comments:
            html_blocks.append(f"<div class='diagram-comment-group'>\n{start_diag}\n{start_comments}</div>")
        else:
            html_blocks.append(start_diag)

    def traverse(pos_id, m_num, white_turn, depth=0, parent_tag="", moves_since_diagram=0, pending_moves=None, path_str=None):
        if pending_moves is None:
            pending_moves = []
        if path_str is None:
            path_str = chap_prefix

        moves = get_children(pos_id)
        if not moves:
            if pending_moves:
                html_blocks.append(f"<p class='moves'>{' '.join(pending_moves)}</p>")
            return

        main_move = moves[0]
        sidelines = moves[1:]

        # Process Main Move
        m_id, san, to_pos, fen, raw_c, v1, v2, v3 = main_move
        main_var = extract_variation_name(v1, v2, v3, exclude_title=chap_title, language=language)
        if main_var and depth > 0:
            if pending_moves:
                html_blocks.append(f"<p class='moves'>{' '.join(pending_moves)}</p>")
                pending_moves = []
            html_blocks.append(f"<div class='mainline-variation-heading'><span class='subvar-badge'>Variante</span> <span class='subvar-title'>{main_var}</span></div>")
        loc_san = format_san(san, language)
        new_path = append_move_to_path(path_str, m_num, white_turn, loc_san)
        
        # Add to continuous move flow
        if white_turn:
            pending_moves.append(f"{m_num}.{loc_san}")
        else:
            if pending_moves and pending_moves[-1].startswith(f"{m_num}."):
                pending_moves[-1] += f" {loc_san}"
            else:
                pending_moves.append(f"{m_num}...{loc_san}")

        clean_text, parsed_anno = extract_clean_comment(raw_c, language)

        def get_transposition_note(orig: dict) -> str:
            t_chap = orig.get("chap_idx", 1)
            t_title = orig.get("chap_title", "")
            if t_chap == chap_idx:
                orig_path = orig.get("san_path", "")
                last_moves = " ".join(orig_path.split()[-2:]) if orig_path else ""
                if last_moves:
                    return f"↳ siehe {last_moves}" if language == "de" else f"↳ see {last_moves}"
                return "↳ siehe oben" if language == "de" else "↳ see above"
            else:
                p_str = ""
                if page_map and t_chap in page_map:
                    p_str = f", S. {page_map[t_chap]}" if language == "de" else f", p. {page_map[t_chap]}"
                if language == "de":
                    return f"↳ Zugumstellung auf <a href='#chapter-{t_chap}' title='{t_title}'>Kapitel {t_chap}</a>{p_str}"
                else:
                    return f"↳ Transposition to <a href='#chapter-{t_chap}' title='{t_title}'>Chapter {t_chap}</a>{p_str}"

        # Transposition Detection for Main Move
        if to_pos in visited_positions:
            orig = visited_positions[to_pos]
            note_text = get_transposition_note(orig)
            inline_html = f"<span class='transposition-inline'>*({note_text})*</span>"
            if pending_moves:
                html_blocks.append(f"<p class='moves'>{' '.join(pending_moves)} {inline_html}</p>")
                pending_moves = []
            else:
                html_blocks.append(f"<p class='transposition-note'>{inline_html}</p>")
            return
        else:
            visited_positions[to_pos] = {
                "chap_idx": chap_idx,
                "chap_title": chap_title,
                "san_path": new_path
            }

            child_moves = get_children(to_pos)
            is_leaf = len(child_moves) == 0
            has_drawings = bool(parsed_anno.get("arrows") or parsed_anno.get("highlights"))

            diag_tracker["plies_since_diagram"] += 1
            if has_drawings:
                should_show_diag = True
            elif depth == 0 and is_leaf:
                # Leaf at the end of the chapter's main line
                should_show_diag = True
            elif diag_tracker["plies_since_diagram"] < 6:
                # Skip diagram if within last 3 full moves (< 6 plies)
                should_show_diag = False
            else:
                is_major_branch = (len(child_moves) >= 3) and (depth == 0)
                is_checkpoint = diag_tracker["plies_since_diagram"] >= 8
                should_show_diag = is_major_branch or is_checkpoint

            has_break = bool(clean_text or should_show_diag)
            next_moves_since_diagram = 0 if should_show_diag else moves_since_diagram + 1

            if has_break:
                # Flush pending moves
                if pending_moves:
                    html_blocks.append(f"<p class='moves'>{' '.join(pending_moves)}</p>")
                    pending_moves = []

                diag_svg = ""
                if should_show_diag:
                    num_prefix = f"{m_num}." if white_turn else f"{m_num}..."
                    caption = f"Stellung nach {num_prefix}{loc_san}" if language == "de" else f"Position after {num_prefix}{loc_san}"
                    diag_svg = render_board_svg(fen, parsed_anno, color=color, caption=caption, size=195)
                    diag_tracker["plies_since_diagram"] = 0

                comment_html = ""
                if clean_text:
                    lines = [l.strip() for l in clean_text.split("\n") if l.strip()]
                    if len(lines) > 1 and any(l.startswith("-") or l.startswith("•") for l in lines[1:]):
                        bullet_items = "".join(f"<li>{l.lstrip('-•').strip()}</li>" for l in lines[1:] if l.strip())
                        comment_html = f"<p>{lines[0]}</p>\n<ul class='book-list'>{bullet_items}</ul>\n"
                    else:
                        comment_html = "".join(f"<p>{line}</p>\n" for line in lines)

                if diag_svg and comment_html:
                    html_blocks.append(f"<div class='diagram-comment-group'>\n{diag_svg}\n{comment_html}</div>")
                elif diag_svg:
                    html_blocks.append(diag_svg)
                elif comment_html:
                    html_blocks.append(comment_html)

            # Traverse Main Line Continuation
            next_white = not white_turn
            next_num = m_num if white_turn else m_num + 1
            traverse(to_pos, next_num, next_white, depth + 1, parent_tag, next_moves_since_diagram, pending_moves, new_path)

        # Render Sidelines
        for s_idx, s_move in enumerate(sidelines):
            s_m_id, s_san, s_to_pos, s_fen, s_raw_c, s_v1, s_v2, s_v3 = s_move
            s_loc_san = format_san(s_san, language)
            s_new_path = append_move_to_path(path_str, m_num, white_turn, s_loc_san)
            s_tag_letter = chr(65 + (s_idx % 26))
            s_tag = f"{parent_tag}{s_tag_letter}" if parent_tag else f"{s_tag_letter}"
            s_num_prefix = f"{m_num}." if white_turn else f"{m_num}..."

            s_clean_text, s_parsed_anno = extract_clean_comment(s_raw_c, language)
            s_has_drawings = bool(s_parsed_anno.get("arrows") or s_parsed_anno.get("highlights"))

            side_var = extract_variation_name(s_v1, s_v2, s_v3, exclude_title=chap_title, language=language)
            var_suffix = f" <span class='variation-name'>– {side_var}</span>" if side_var else ""

            # Direct transposition on sideline move
            if s_to_pos in visited_positions:
                orig = visited_positions[s_to_pos]
                note_text = get_transposition_note(orig)
                inline_html = f"<span class='transposition-inline'>*({note_text})*</span>"
                html_blocks.append(f"<div class='variation-heading'><span class='sideline-tag'>{s_tag})</span> <span class='moves'>{s_num_prefix}{s_loc_san}</span>{var_suffix} {inline_html}</div>")
                continue

            # Check if White's sideline move + Black's reply can merge into heading (Option 1)
            s_child_moves = get_children(s_to_pos)
            merged_reply = None
            if white_turn and not s_clean_text and not s_has_drawings and len(s_child_moves) >= 1:
                merged_reply = s_child_moves[0]

            if merged_reply:
                r_m_id, r_san, r_to_pos, r_fen, r_raw_c, r_v1, r_v2, r_v3 = merged_reply
                r_loc_san = format_san(r_san, language)
                r_new_path = append_move_to_path(s_new_path, m_num, False, r_loc_san)
                visited_positions[s_to_pos] = {
                    "chap_idx": chap_idx,
                    "chap_title": chap_title,
                    "san_path": s_new_path
                }

                if not side_var:
                    side_var = extract_variation_name(r_v1, r_v2, r_v3, exclude_title=chap_title, language=language)
                    var_suffix = f" <span class='variation-name'>– {side_var}</span>" if side_var else ""

                r_clean_text, r_parsed_anno = extract_clean_comment(r_raw_c, language)
                r_has_drawings = bool(r_parsed_anno.get("arrows") or r_parsed_anno.get("highlights"))

                if r_to_pos in visited_positions:
                    orig = visited_positions[r_to_pos]
                    note_text = get_transposition_note(orig)
                    inline_html = f"<span class='transposition-inline'>*({note_text})*</span>"
                    html_blocks.append(f"<div class='variation-heading'><span class='sideline-tag'>{s_tag})</span> <span class='moves'>{m_num}.{s_loc_san} {r_loc_san}</span>{var_suffix} {inline_html}</div>")
                else:
                    visited_positions[r_to_pos] = {
                        "chap_idx": chap_idx,
                        "chap_title": chap_title,
                        "san_path": r_new_path
                    }
                    heading_html = f"<div class='variation-heading'><span class='sideline-tag'>{s_tag})</span> <span class='moves'>{m_num}.{s_loc_san} {r_loc_san}</span>{var_suffix}</div>"

                    r_child_moves = get_children(r_to_pos)
                    r_is_leaf = len(r_child_moves) == 0
                    diag_tracker["plies_since_diagram"] += 1
                    if r_has_drawings:
                        r_should_show = True
                    elif diag_tracker["plies_since_diagram"] < 6:
                        r_should_show = False
                    else:
                        r_should_show = bool(r_clean_text and diag_tracker["plies_since_diagram"] >= 8)

                    diag_svg = ""
                    r_next_moves = 0 if r_should_show else moves_since_diagram + 1
                    if r_should_show:
                        caption = f"Stellung nach {m_num}...{r_loc_san}" if language == "de" else f"Position after {m_num}...{r_loc_san}"
                        diag_svg = render_board_svg(r_fen, r_parsed_anno, color=color, caption=caption, size=195)
                        diag_tracker["plies_since_diagram"] = 0

                    comment_html = ""
                    if r_clean_text:
                        lines = [line.strip() for line in r_clean_text.split("\n") if line.strip()]
                        if len(lines) > 1 and any(l.startswith("-") or l.startswith("•") for l in lines[1:]):
                            bullet_items = "".join(f"<li>{l.lstrip('-•').strip()}</li>" for l in lines[1:] if l.strip())
                            comment_html = f"<p>{lines[0]}</p>\n<ul class='book-list'>{bullet_items}</ul>\n"
                        else:
                            comment_html = "".join(f"<p>{line}</p>\n" for line in lines)

                    if diag_svg and comment_html:
                        html_blocks.append(f"<div class='diagram-comment-group'>\n{heading_html}\n{diag_svg}\n{comment_html}</div>")
                    elif diag_svg:
                        html_blocks.append(f"<div class='diagram-comment-group'>\n{heading_html}\n{diag_svg}\n</div>")
                    else:
                        html_blocks.append(heading_html)
                        if comment_html:
                            html_blocks.append(comment_html)

                    traverse(r_to_pos, m_num + 1, True, depth + 1, parent_tag=f"{s_tag}.", moves_since_diagram=r_next_moves, pending_moves=[], path_str=r_new_path)
            else:
                visited_positions[s_to_pos] = {
                    "chap_idx": chap_idx,
                    "chap_title": chap_title,
                    "san_path": s_new_path
                }
                heading_html = f"<div class='variation-heading'><span class='sideline-tag'>{s_tag})</span> <span class='moves'>{s_num_prefix}{s_loc_san}</span>{var_suffix}</div>"

                s_is_leaf = len(s_child_moves) == 0
                diag_tracker["plies_since_diagram"] += 1
                if s_has_drawings:
                    s_should_show = True
                elif diag_tracker["plies_since_diagram"] < 6:
                    s_should_show = False
                else:
                    s_should_show = bool(s_clean_text and diag_tracker["plies_since_diagram"] >= 8)

                diag_svg = ""
                s_next_moves = 0 if s_should_show else moves_since_diagram + 1
                if s_should_show:
                    s_caption = f"Stellung nach {s_num_prefix}{s_loc_san}" if language == "de" else f"Position after {s_num_prefix}{s_loc_san}"
                    diag_svg = render_board_svg(s_fen, s_parsed_anno, color=color, caption=s_caption, size=195)
                    diag_tracker["plies_since_diagram"] = 0

                comment_html = ""
                if s_clean_text:
                    lines = [line.strip() for line in s_clean_text.split("\n") if line.strip()]
                    if len(lines) > 1 and any(l.startswith("-") or l.startswith("•") for l in lines[1:]):
                        bullet_items = "".join(f"<li>{l.lstrip('-•').strip()}</li>" for l in lines[1:] if l.strip())
                        comment_html = f"<p>{lines[0]}</p>\n<ul class='book-list'>{bullet_items}</ul>\n"
                    else:
                        comment_html = "".join(f"<p>{line}</p>\n" for line in lines)

                if diag_svg and comment_html:
                    html_blocks.append(f"<div class='diagram-comment-group'>\n{heading_html}\n{diag_svg}\n{comment_html}</div>")
                elif diag_svg:
                    html_blocks.append(f"<div class='diagram-comment-group'>\n{heading_html}\n{diag_svg}\n</div>")
                else:
                    html_blocks.append(heading_html)
                    if comment_html:
                        html_blocks.append(comment_html)

                next_white = not white_turn
                next_num = m_num if white_turn else m_num + 1
                traverse(s_to_pos, next_num, next_white, depth + 1, parent_tag=f"{s_tag}.", moves_since_diagram=s_next_moves, pending_moves=[], path_str=s_new_path)

    traverse(start_pos_id, start_move_num, is_white_turn, moves_since_diagram=0, pending_moves=[], path_str=chap_prefix)
    return "\n".join(html_blocks)

def discover_chapters(
    conn: sqlite3.Connection,
    color: str = 'b',
    level: Optional[int] = None,
    language: str = "de"
) -> List[dict]:
    """Identifies opening chapters from repertoire tree without translation."""
    cur = conn.cursor()
    lvl_filter = f"AND rm.level <= {level}" if level is not None else ""

    pos_cols = {r[1] for r in cur.execute("PRAGMA table_info(positions)").fetchall()}
    v1_expr = "p.variation_1" if "variation_1" in pos_cols else "NULL"
    v2_expr = "p.variation_2" if "variation_2" in pos_cols else "NULL"
    v3_expr = "p.variation_3" if "variation_3" in pos_cols else "NULL"

    cur.execute(f"""
        SELECT m.id, m.san, m.from_position_id, m.to_position_id, p.fen, {v1_expr}, {v2_expr}, {v3_expr}, m.priority_score
        FROM repertoire_moves rm
        JOIN moves m ON rm.move_id = m.id
        JOIN positions p ON m.to_position_id = p.id
        WHERE rm.is_active = 1 {lvl_filter}
    """)
    all_moves = cur.fetchall()

    children = {}
    for m_id, san, from_pos, to_pos, fen, v1, v2, v3, prio in all_moves:
        children.setdefault(from_pos, []).append((m_id, san, to_pos, fen, v1, v2, v3, prio))

    def count_subtree(pos_id, visited=None):
        if visited is None:
            visited = set()
        if pos_id in visited:
            return 0
        visited.add(pos_id)
        cnt = len(children.get(pos_id, []))
        for _, _, to_p, _, _, _, _, _ in children.get(pos_id, []):
            cnt += count_subtree(to_p, visited)
        return cnt

    def resolve_name(raw: Optional[str]) -> str:
        if not raw or not str(raw).strip():
            return ""
        return parse_variation_name(str(raw).strip(), lang=language, default_lang="de" if language == "de" else "en")

    def get_subvars(pos_id, visited=None):
        if visited is None:
            visited = set()
        if pos_id in visited:
            return []
        visited.add(pos_id)
        subvars = []
        for _, _, to_p, _, v1, v2, v3, _ in children.get(pos_id, []):
            raw_v = (v2 or v3 or "").strip()
            v = resolve_name(raw_v)
            if v and v not in subvars:
                subvars.append(v)
            for sub in get_subvars(to_p, visited):
                if sub not in subvars:
                    subvars.append(sub)
        return subvars

    chapters = []

    if color == 'b':
        # Start looking from pos 3 (after 1.e4 e5) or from pos 1
        branch_roots = children.get(3, [])
        if not branch_roots:
            # Fallback to root children if not standard 1.e4 e5
            branch_roots = children.get(1, [])

        for m_id, san, to_pos, fen, v1, v2, v3, prio in branch_roots:
            loc_san = format_san(san, language)
            if san == "Nf3":
                for m2_id, san2, to_pos2, fen2, v1_2, v2_2, v3_2, prio2 in children.get(to_pos, []):
                    loc_san2 = format_san(san2, language)
                    for m3_id, san3, to_pos3, fen3, v1_3, v2_3, v3_3, prio3 in children.get(to_pos2, []):
                        loc_san3 = format_san(san3, language)
                        cnt = count_subtree(to_pos3) + 1
                        title = resolve_name(v1_3 or v2_3 or v3_3)
                        if not title:
                            # Check if immediate reply has a variation name
                            for _, _, child_pos, _, cv1, cv2, cv3, _ in children.get(to_pos3, []):
                                c_title = resolve_name(cv1 or cv2 or cv3)
                                if c_title:
                                    title = c_title
                                    break
                        if not title:
                            title = f"3.{loc_san3}"

                        subvars = get_subvars(to_pos3)
                        chapters.append({
                            "title": title,
                            "san_prefix": f"1.e4 e5 2.{loc_san} {loc_san2} 3.{loc_san3}",
                            "start_pos_id": to_pos3,
                            "start_move_num": 3,
                            "is_white_turn": False,
                            "move_count": cnt,
                            "priority_score": prio3,
                            "subvars": subvars
                        })
            else:
                cnt = count_subtree(to_pos) + 1
                title = resolve_name(v1 or v2 or v3)
                if not title:
                    # Check if immediate reply has a variation name
                    for _, _, child_pos, _, cv1, cv2, cv3, _ in children.get(to_pos, []):
                        c_title = resolve_name(cv1 or cv2 or cv3)
                        if c_title:
                            title = c_title
                            break
                if not title:
                    title = f"2.{loc_san}"

                subvars = get_subvars(to_pos)
                chapters.append({
                    "title": title,
                    "san_prefix": f"1.e4 e5 2.{loc_san}",
                    "start_pos_id": to_pos,
                    "start_move_num": 2,
                    "is_white_turn": False,
                    "move_count": cnt,
                    "priority_score": prio,
                    "subvars": subvars
                })
    else:
        # Repertoire for White
        for m_id, san, to_pos, fen, v1, v2, v3, prio in children.get(1, []):
            loc_san = format_san(san, language)
            for m2_id, san2, to_pos2, fen2, v1_2, v2_2, v3_2, prio2 in children.get(to_pos, []):
                loc_san2 = format_san(san2, language)
                cnt = count_subtree(to_pos2) + 1
                title = resolve_name(v1_2 or v2_2 or v3_2)
                if not title:
                    for _, _, child_pos, _, cv1, cv2, cv3, _ in children.get(to_pos2, []):
                        c_title = resolve_name(cv1 or cv2 or cv3)
                        if c_title:
                            title = c_title
                            break
                if not title:
                    title = f"1.{loc_san} {loc_san2}"

                subvars = get_subvars(to_pos2)
                chapters.append({
                    "title": title,
                    "san_prefix": f"1.{loc_san} {loc_san2}",
                    "start_pos_id": to_pos2,
                    "start_move_num": 2,
                    "is_white_turn": True,
                    "move_count": cnt,
                    "priority_score": prio2,
                    "subvars": subvars
                })

    # Sort chapters strictly by priority_score descending (with move_count tiebreaker)
    chapters.sort(key=lambda c: (c.get("priority_score", 0.0), c.get("move_count", 0)), reverse=True)
    return chapters


class VarNode:
    def __init__(self, san: str = "", m_num: int = 1, is_white: bool = True, to_pos: Optional[int] = None, var_name: Optional[str] = None):
        self.san = san
        self.m_num = m_num
        self.is_white = is_white
        self.to_pos = to_pos
        self.var_name = var_name
        self.children = []
        self.chapter_idx = None
        self.transposition_note = None


def generate_variation_index(
    conn: sqlite3.Connection,
    chapters: List[dict],
    color: str = 'b',
    level: Optional[int] = None,
    language: str = "de",
    page_map: Optional[Dict[Any, int]] = None
) -> Tuple[str, int]:
    """
    Builds a dense, hierarchical Varianten-Index (Index of Variations)
    at the end of the textbook with Unicode tree connectors, dotted leaders,
    explicit transposition hints (pointing to the exact move sequence),
    and clickable links/page numbers to corresponding chapters.
    """
    cur = conn.cursor()
    lvl_filter = f"AND rm.level <= {level}" if level is not None else ""

    # Map chapter start positions
    pos_to_chap = {}
    for idx, c in enumerate(chapters, start=1):
        pos_to_chap[c["start_pos_id"]] = idx

    pos_cols = {r[1] for r in cur.execute("PRAGMA table_info(positions)").fetchall()}
    v1_expr = "p.variation_1" if "variation_1" in pos_cols else "NULL"
    v2_expr = "p.variation_2" if "variation_2" in pos_cols else "NULL"
    v3_expr = "p.variation_3" if "variation_3" in pos_cols else "NULL"

    def get_moves_for_pos(p_id):
        cur.execute(f"""
            SELECT m.id, m.san, m.to_position_id, {v1_expr}, {v2_expr}, {v3_expr}
            FROM repertoire_moves rm
            JOIN moves m ON rm.move_id = m.id
            JOIN positions p ON m.to_position_id = p.id
            WHERE m.from_position_id = ? AND rm.is_active = 1 {lvl_filter}
            ORDER BY m.priority_score DESC
        """, (p_id,))
        return cur.fetchall()

    def format_single_move(san, m_num, is_white, prev_was_white=False):
        loc = format_san(san, language)
        if is_white:
            return f"{m_num}.{loc}"
        else:
            return loc if prev_was_white else f"{m_num}...{loc}"

    def build_tree(pos_id=1, m_num=1, is_white=True, visited=None, active_chap=None, path_moves=None):
        if visited is None:
            visited = {}
        if path_moves is None:
            path_moves = []

        node = VarNode("", m_num, is_white, pos_id)
        if pos_id in pos_to_chap:
            active_chap = pos_to_chap[pos_id]
        node.chapter_idx = active_chap

        moves = get_moves_for_pos(pos_id)
        for m_id, san, to_p, v1, v2, v3 in moves:
            child_is_white = not is_white
            child_m_num = m_num if is_white else m_num + 1
            child_chap = pos_to_chap.get(to_p, active_chap)
            var_lbl = extract_variation_name(v1, v2, v3, language=language)
            child_node = VarNode(san, m_num, is_white, to_p, var_name=var_lbl)
            child_node.chapter_idx = child_chap

            loc = format_san(san, language)
            move_label = f"{m_num}.{loc}" if is_white else f"{m_num}...{loc}"
            curr_path = path_moves + [move_label]

            if to_p in visited:
                orig = visited[to_p]
                orig_chap = orig.get("chap_idx")
                orig_path = orig.get("path_moves", [])

                # Find first divergence move
                i = 0
                while i < len(orig_path) and i < len(curr_path) and orig_path[i] == curr_path[i]:
                    i += 1
                diverged_move = orig_path[i] if i < len(orig_path) else ""

                if orig_chap == child_chap or orig_chap is None:
                    hint = f"↳ siehe {diverged_move}" if diverged_move else "↳ siehe Hauptvariante"
                    if language == "en":
                        hint = f"↳ see {diverged_move}" if diverged_move else "↳ see main line"
                    child_node.transposition_note = hint
                else:
                    div_str = f": {diverged_move}" if diverged_move else ""
                    child_node.transposition_note = (
                        f"↳ siehe Kap. {orig_chap}{div_str}" if language == "de"
                        else f"↳ see Chap. {orig_chap}{div_str}"
                    )
                child_node.chapter_idx = orig_chap or child_chap
                node.children.append(child_node)
            else:
                visited[to_p] = {"chap_idx": child_chap, "pos_id": to_p, "path_moves": curr_path}
                sub_tree = build_tree(to_p, child_m_num, child_is_white, visited, child_chap, curr_path)
                child_node.children = sub_tree.children
                child_node.chapter_idx = sub_tree.chapter_idx or child_chap
                node.children.append(child_node)

        return node

    root_pos = 1
    root = build_tree(root_pos, 1, True, {}, None, [])

    var_count = 0
    MAX_CHAIN_MOVES = 6  # Keeps each variation entry strictly on a single clean line

    def render_rows(node, prefix="", is_last=True):
        nonlocal var_count
        rows = []
        chain = []
        curr = node

        if curr.san:
            chain.append(format_single_move(curr.san, curr.m_num, curr.is_white))

        node_vars = [curr.var_name] if curr.var_name else []
        has_more = False
        while len(curr.children) == 1 and not curr.children[0].transposition_note and (curr.children[0].chapter_idx == curr.chapter_idx or curr.chapter_idx is None):
            child = curr.children[0]
            if child.var_name and child.var_name not in node_vars:
                node_vars.append(child.var_name)
            if len(chain) >= MAX_CHAIN_MOVES:
                has_more = True
                while len(curr.children) == 1 and not curr.children[0].transposition_note:
                    curr = curr.children[0]
                    if curr.var_name and curr.var_name not in node_vars:
                        node_vars.append(curr.var_name)
                break
            prev_is_white = curr.is_white
            chain.append(format_single_move(child.san, child.m_num, child.is_white, prev_was_white=prev_is_white))
            curr = child

        if has_more:
            chain.append("...")

        chain_text = " ".join(chain)
        chap_idx = curr.chapter_idx
        trans_text = f" <span class='index-trans'>({curr.transposition_note})</span>" if curr.transposition_note else ""
        var_text = f" <span class='index-varname'>({' · '.join(node_vars)})</span>" if node_vars else ""

        branch_char = "└── " if is_last else "├── "

        if chain_text:
            moves_html = f"<span class='index-moves'>{chain_text}</span>{var_text}{trans_text}"
            if not curr.children:
                var_count += 1
                chap_label = f"Kapitel {chap_idx}" if language == "de" else f"Chapter {chap_idx}"
                chap_link = f"<a class='index-chap-link' href='#chapter-{chap_idx}'>{chap_label}</a>" if chap_idx else ""
                page_span = ""
                if page_map and chap_idx in page_map:
                    page_span = f" <span class='index-page'>(S. {page_map[chap_idx]})</span>" if language == "de" else f" <span class='index-page'>(p. {page_map[chap_idx]})</span>"
                rows.append(f"""
                <div class="index-row">
                    <span class="index-branch"><span class="index-prefix">{prefix}{branch_char}</span>{moves_html}</span>
                    <span class="index-dots"></span>
                    <span class="index-target">{chap_link}{page_span}</span>
                </div>
                """)
            else:
                rows.append(f"""
                <div class="index-row">
                    <span class="index-branch"><span class="index-prefix">{prefix}{branch_char}</span>{moves_html}</span>
                </div>
                """)
                new_prefix = prefix + ("    " if is_last else "│   ")
                for i, c in enumerate(curr.children):
                    c_last = (i == len(curr.children) - 1)
                    rows.extend(render_rows(c, new_prefix, c_last))
        else:
            for i, c in enumerate(curr.children):
                c_last = (i == len(curr.children) - 1)
                rows.extend(render_rows(c, prefix, c_last))

        return rows

    html_rows = render_rows(root)

    idx_heading = "Varianten-Index" if language == "de" else "Index of Variations"
    idx_sub = (
        "Dichte Übersicht aller Repertoire-Varianten, Zugumstellungen und Querverweise auf die Kapitel."
        if language == "de" else
        "Dense overview of all repertoire variations, transpositions, and chapter cross-references."
    )

    index_html = f"""
    <div class="index-section" id="variation-index">
        <div class="index-header">
            <h2 class="index-title">{idx_heading}</h2>
            <div class="index-sub">{idx_sub}</div>
        </div>
        <div class="index-tree-box">
            {"".join(html_rows)}
        </div>
    </div>
    """

    return index_html, var_count


def export_repertoire_book(
    db_path: str,
    output_path: str,
    output_format: str = "html",
    level: Optional[int] = None,
    language: str = "de",
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> str:
    """
    Main export entry point: generates complete repertoire textbook in HTML or PDF.
    """
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"Datenbank nicht gefunden: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        if progress_callback:
            progress_callback(5, 100, "Lese Repertoire-Metadaten...")

        # Load metadata
        metadata = {}
        try:
            cur.execute("SELECT key, value FROM metadata")
            for k, v in cur.fetchall():
                metadata[k] = v
        except Exception:
            pass

        color = metadata.get("color", "b")
        repo_name = metadata.get("repertoire_display_name") or metadata.get("name") or "Repertoire"
        metadata["name"] = repo_name

        # Resolve course cover image as base64 data URI for textbook cover header
        course_icon_data_uri = get_course_icon_data_uri(db_path, repo_name=repo_name)
        metadata["course_icon_data_uri"] = course_icon_data_uri

        # Determine level name
        level_name = "Alle Level" if language == "de" else "All Levels"
        if level is not None:
            try:
                cur.execute("SELECT name FROM repertoire_levels WHERE `order` = ?", (level,))
                r = cur.fetchone()
                if r and r[0]:
                    level_name = f"Level {level}: {r[0]}"
            except Exception:
                level_name = f"Level {level}"
        metadata["level_name"] = level_name

        if progress_callback:
            progress_callback(15, 100, "Erkenne Eröffnungskapitel...")

        chapters = discover_chapters(conn, color=color, level=level, language=language)
        if not chapters:
            # Fallback chapter from root
            chapters = [{
                "title": "Hauptvariante",
                "san_prefix": "Ausgangsstellung",
                "start_pos_id": 1,
                "start_move_num": 1,
                "is_white_turn": True,
                "move_count": 50
            }]

        visited_positions = {}
        total_chapters = len(chapters)
        for idx, chap in enumerate(chapters, start=1):
            if progress_callback:
                pct = 20 + int(50 * (idx / max(1, total_chapters)))
                msg = f"Generiere Kapitel {idx}/{total_chapters}: {chap['title']}..."
                if progress_callback(pct, 100, msg) is True:
                    conn.close()
                    return ""

            content_html = flatten_subtree(
                conn=conn,
                start_pos_id=chap["start_pos_id"],
                start_move_num=chap["start_move_num"],
                is_white_turn=chap["is_white_turn"],
                color=color,
                level=level,
                language=language,
                visited_positions=visited_positions,
                chap_idx=idx,
                chap_title=chap["title"],
                chap_prefix=chap["san_prefix"]
            )
            chap["content_html"] = content_html

        if progress_callback:
            progress_callback(75, 100, "Erstelle Varianten-Index...")

        var_index_html, var_count = generate_variation_index(
            conn=conn,
            chapters=chapters,
            color=color,
            level=level,
            language=language
        )

        if progress_callback:
            progress_callback(85, 100, "Erstelle HTML-Dokument...")

        full_html = build_book_html(
            metadata,
            chapters,
            language=language,
            variation_index_html=var_index_html,
            variation_count=var_count
        )

        # Determine HTML file path
        base_dir = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(base_dir, exist_ok=True)

        if output_format.lower() == "pdf":
            abs_output_path = os.path.abspath(output_path)

            # Pre-check: Ensure destination path is writable and not locked by another program
            if os.path.exists(abs_output_path):
                try:
                    with open(abs_output_path, "r+b"):
                        pass
                except Exception:
                    raise RuntimeError(
                        f"Die Zieldatei '{os.path.basename(abs_output_path)}' ist derzeit geöffnet oder schreibgeschützt.\n\n"
                        "Bitte schließen Sie die Datei in Ihrem PDF-Programm (z. B. Edge, Acrobat oder Browser) und versuchen Sie es erneut."
                    )

            temp_dir = tempfile.gettempdir()
            html_temp_path = os.path.join(temp_dir, f"fenix_book_{uuid.uuid4().hex}.html")

            try:
                with open(html_temp_path, "w", encoding="utf-8") as f:
                    f.write(full_html)

                if progress_callback:
                    if progress_callback(90, 100, "Erstelle PDF-Datei...") is True:
                        return ""

                browser_path = find_headless_browser()
                if not browser_path:
                    raise RuntimeError("Kein Chromium-Browser (Microsoft Edge oder Google Chrome) für direkten PDF-Export gefunden.")

                res = _run_chromium_pdf(browser_path, html_temp_path, abs_output_path)
                if not os.path.isfile(abs_output_path) or os.path.getsize(abs_output_path) == 0:
                    err = (res.stderr or res.stdout).decode("utf-8", errors="ignore").strip() if res else ""
                    if not err:
                        err = f"Chromium beendete die PDF-Erstellung ohne Fehlermeldung (Exit-Code: {res.returncode if res else 'None'}). Möglicherweise übersteigt der Umfang des gesamten Repertoires den Speicher des PDF-Druckers. Bitte exportieren Sie mit Level-Begrenzung (z. B. Level 1 oder 2) oder wählen Sie HTML als Ausgabeformat."
                    raise RuntimeError(f"PDF-Erstellung fehlgeschlagen: {err}")

                # Inspect generated PDF for exact chapter and index page numbers using fitz
                page_map = {}
                try:
                    import fitz
                    doc = fitz.open(abs_output_path)
                    for p_no in range(1, len(doc)):
                        txt = doc[p_no].get_text().upper()
                        for c_i in range(1, len(chapters) + 1):
                            if c_i not in page_map and f"KAPITEL {c_i}" in txt:
                                page_map[c_i] = p_no + 1
                        if "index" not in page_map and "VARIANTEN-INDEX" in txt:
                            page_map["index"] = p_no + 1
                    doc.close()
                except Exception:
                    pass

                # If page numbers were successfully identified, do second pass to embed exact page numbers
                if page_map:
                    if progress_callback:
                        if progress_callback(95, 100, "Betten exakte Seitenzahlen in PDF ein...") is True:
                            return ""

                    # Pass 2: Re-flatten chapters with exact page numbers for in-text transpositions
                    visited_positions_pass2 = {}
                    for idx, chap in enumerate(chapters, start=1):
                        chap["content_html"] = flatten_subtree(
                            conn=conn,
                            start_pos_id=chap["start_pos_id"],
                            start_move_num=chap["start_move_num"],
                            is_white_turn=chap["is_white_turn"],
                            color=color,
                            level=level,
                            language=language,
                            visited_positions=visited_positions_pass2,
                            chap_idx=idx,
                            chap_title=chap["title"],
                            chap_prefix=chap["san_prefix"],
                            page_map=page_map
                        )

                    var_index_html_final, _ = generate_variation_index(
                        conn=conn,
                        chapters=chapters,
                        color=color,
                        level=level,
                        language=language,
                        page_map=page_map
                    )
                    full_html_final = build_book_html(
                        metadata,
                        chapters,
                        language=language,
                        variation_index_html=var_index_html_final,
                        variation_count=var_count,
                        page_map=page_map
                    )
                    with open(html_temp_path, "w", encoding="utf-8") as f:
                        f.write(full_html_final)
                    res = _run_chromium_pdf(browser_path, html_temp_path, abs_output_path)

                if not os.path.isfile(abs_output_path) or os.path.getsize(abs_output_path) == 0:
                    err = (res.stderr or res.stdout).decode("utf-8", errors="ignore").strip() if res else ""
                    if not err:
                        err = f"Chromium beendete die PDF-Erstellung ohne Fehlermeldung (Exit-Code: {res.returncode if res else 'None'}). Möglicherweise übersteigt der Umfang des gesamten Repertoires den Speicher des PDF-Druckers. Bitte exportieren Sie mit Level-Begrenzung (z. B. Level 1 oder 2) oder wählen Sie HTML als Ausgabeformat."
                    raise RuntimeError(f"PDF-Erstellung fehlgeschlagen: {err}")

                final_path = abs_output_path
            finally:
                if os.path.isfile(html_temp_path):
                    try:
                        os.remove(html_temp_path)
                    except Exception:
                        pass
        else:
            # Standard HTML output
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(full_html)
            final_path = output_path

        if progress_callback:
            progress_callback(100, 100, "Export abgeschlossen!")

    finally:
        try:
            conn.close()
        except Exception:
            pass
    return final_path
