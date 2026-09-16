import os
import io
import re
import shutil
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Callable, Any
import chess
import chess.pgn

from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import get_meta, set_meta
from opening_fenix.core.utils import (
    get_user_dir,
    get_repertoire_db_path,
    initialize_repertoire_assets,
    combine_comments,
    normalize_castling_uci,
    natural_sort_key
)
from opening_fenix.core.services.repair_service import repair_repertoire_health
from opening_fenix.core.logger import logger
from opening_fenix.core.translation import tr_ui

# Supported classification target categories
CATEGORY_LEVEL_1 = "level_1"   # Quickstarter / Basics (Level 1)
CATEGORY_LEVEL_2 = "level_2"   # Main Course / Deep Theory (Level 2)
CATEGORY_MOTIVES = "motives"   # Typical Motives -> Typical Motives.pgn
CATEGORY_TACTICS = "tactics"   # Puzzles / Tactics -> Tactics/Tactics.pgn
CATEGORY_MODEL = "model"       # Model / Reference Games -> Model Games.pgn
CATEGORY_INTRO = "intro"       # Introductions -> Introductions from pgn import.pgn
CATEGORY_IGNORE = "ignore"     # Skipped / Ignored completely

@dataclass
class CourseGameInfo:
    game_id: int          # Global 0-based index across all scanned games
    file_path: str        # Path of the source PGN file
    title: str            # White header / Line name
    chapter_name: str     # Black header / Chapter name
    eco: str = ""
    fen: str = ""
    is_puzzle: bool = False
    is_model: bool = False
    is_intro: bool = False
    target_type: str = "" # Inferred default target (e.g. level_1, level_2, tactics, etc.)

@dataclass
class CourseChapterInfo:
    name: str
    game_count: int = 0
    sample_titles: List[str] = field(default_factory=list)
    target_type: str = CATEGORY_LEVEL_2
    embedded_puzzles: int = 0
    embedded_models: int = 0
    embedded_intros: int = 0
    games: List[CourseGameInfo] = field(default_factory=list)

@dataclass
class CourseAnalysisResult:
    pgn_paths: List[str] = field(default_factory=list)
    suggested_repo_name: str = ""
    suggested_color: str = "w"
    suggested_elo: str = "high"
    total_games: int = 0
    chapters: List[CourseChapterInfo] = field(default_factory=list)
    category_counts: Dict[str, int] = field(default_factory=dict)
    cover_image_path: Optional[str] = None
    pgn_path: str = ""

    def __post_init__(self):
        if not self.pgn_path and self.pgn_paths:
            self.pgn_path = self.pgn_paths[0]
        elif self.pgn_path and not self.pgn_paths:
            self.pgn_paths = [self.pgn_path]

@dataclass
class CourseImportPlan:
    repo_name: str
    side: str
    chapter_targets: Dict[str, str]
    pgn_paths: List[str] = field(default_factory=list)
    pgn_path: Optional[str] = None
    cover_image_path: Optional[str] = None
    target_lang: str = "de"
    game_targets: Dict[int, str] = field(default_factory=dict)
    elo: str = "high"

    def __post_init__(self):
        if not self.pgn_paths and self.pgn_path:
            self.pgn_paths = [self.pgn_path]
        elif self.pgn_paths and not self.pgn_path:
            self.pgn_path = self.pgn_paths[0]

@dataclass
class CourseImportResult:
    success: bool
    message: str
    repo_name: str = ""
    level_1_moves: int = 0
    level_2_moves: int = 0
    tactics_games: int = 0
    model_games: int = 0
    motives_games: int = 0
    intro_games_saved: int = 0
    intro_games_skipped: int = 0
    ignored_games: int = 0
    embedded_puzzles: int = 0
    embedded_models: int = 0
    embedded_intros: int = 0

class SanitizedPGNReader:
    """Wrapper around a file object to strip empty [FEN \"\"] tags that crash python-chess."""
    def __init__(self, fp):
        self.fp = fp
    
    def readline(self):
        line = self.fp.readline()
        if not line:
            return line
        s = line.strip()
        if s.startswith('[FEN ""') or s.startswith("[FEN ''"):
            return "\n"
        return line
        
    def tell(self):
        return self.fp.tell()

def sanitize_repertoire_name(name: str) -> str:
    """Sanitizes a course name so it is valid for filesystem directory and DB names."""
    name = name.replace(":", " - ")
    for ch in r'\/*?"<>|':
        name = name.replace(ch, "")
    return re.sub(r'\s+', ' ', name).strip()

def suggest_course_name_from_paths(paths: List[str]) -> str:
    """Derives a clean repertoire name, stripping Part 1 / Part 2 suffixes if multiple parts."""
    if not paths:
        return "New Course"
    names = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    if len(names) == 1:
        name = names[0]
    else:
        name = os.path.commonprefix(names).rstrip(" -_–—")
        if len(name) < 4:
            name = names[0]
    # Strip trailing part designations: "- Part 1", "Part 2", "- Part", "Vol 1", etc.
    name = re.sub(r'[\s\-–—]+(Part|Teil|Volume|Vol)(\b|\s*\d+.*)$', '', name, flags=re.IGNORECASE).rstrip(" -_–—")
    return sanitize_repertoire_name(name)

def classify_chapter(name: str) -> str:
    """
    Classifies a chapter/section name into:
    - 'level_1' (Quickstarter / Basics)
    - 'level_2' (Deep Theory / Main)
    - 'motives' (Typical Motives / Ideas)
    - 'tactics' (Training exercises, Tactics, Drills)
    - 'model' (Model Games, Reference Games)
    - 'intro' (Introductions, Overviews)
    """
    n = name.strip().lower()

    # 1. Quickstarter / Schnellstarter takes precedence
    if re.search(r'(quickstarter|schnellstarter)', n):
        return CATEGORY_LEVEL_1

    # 2. Introduction / Einleitung / Overview / Info
    if "[%info]" in n or "[info]" in n:
        return CATEGORY_INTRO
    if re.search(r'\b(introduction|einleitung|overview|überblick|ueberblick|about the author|preface|vorwort|intro|infos|information|informationen)\b', n):
        return CATEGORY_INTRO
    if re.search(r'^\s*(info\b|intro\b)', n):
        return CATEGORY_INTRO

    # 3. Motives / Typische Motive
    if re.search(r'(typical motive|typische motive|motives|motive|typical ideas|themes)', n):
        return CATEGORY_MOTIVES

    # 4. Tactics / Puzzles / Exercises
    if re.search(r'(training exercise|tactics|taktik|puzzle|tactical|drills)', n):
        return CATEGORY_TACTICS

    # 5. Model / Reference Games
    if re.search(r'(model game|reference game|musterpartie|example game)', n):
        return CATEGORY_MODEL

    # 6. Default to Level 2 (Deep Theory)
    return CATEGORY_LEVEL_2

def is_header_intro(headers: Any) -> bool:
    """Checks whether PGN headers represent an introduction or informational game."""
    if not hasattr(headers, "get"):
        return False
    white = headers.get("White", "").strip()
    black = headers.get("Black", "").strip()
    event = headers.get("Event", "").strip()
    section = headers.get("Section", "").strip()
    annotator = headers.get("Annotator", "").strip()
    
    for h_val in (white, black, event, section, annotator):
        if not h_val:
            continue
        h_lower = h_val.lower()
        if "[%info]" in h_lower or "[info]" in h_lower:
            return True
        if re.search(r'(?i)^\s*(\[%info\]|\[info\]|info\b|intro\b|introduction\b|einleitung\b|overview\b|information\b)', h_val):
            return True

    intro_keywords = r'(?i)\b(introduction|einleitung|overview|überblick|ueberblick|about the author|preface|vorwort|informational)\b'
    if re.search(intro_keywords, white) or re.search(intro_keywords, event) or re.search(intro_keywords, section):
        return True
        
    return False

def is_header_puzzle(headers: Any) -> bool:
    """Checks whether PGN headers represent a puzzle or tactical exercise."""
    fen = headers.get("FEN", "").strip() if hasattr(headers, "get") else ""
    if fen and fen != chess.STARTING_FEN and fen != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1":
        return True
    white = headers.get("White", "").strip() if hasattr(headers, "get") else ""
    event = headers.get("Event", "").strip() if hasattr(headers, "get") else ""
    puzzle_keywords = r'(?i)\b(puzzle|training exercise|exercise|tactic|tactics|taktik|taktikaufgabe|drill|find the|attacking plan|trapping plan|fork tactic)\b'
    if re.search(puzzle_keywords, white) or re.search(puzzle_keywords, event):
        return True
    return False

def is_header_model(headers: Any) -> bool:
    """Checks whether PGN headers represent a model/reference game."""
    white = headers.get("White", "").strip() if hasattr(headers, "get") else ""
    black = headers.get("Black", "").strip() if hasattr(headers, "get") else ""
    event = headers.get("Event", "").strip() if hasattr(headers, "get") else ""
    model_keywords = r'(?i)\b(model game|reference game|musterpartie|example game)\b'
    if re.search(model_keywords, white) or re.search(model_keywords, black) or re.search(model_keywords, event):
        return True
    return False

def is_game_intro(game: chess.pgn.Game) -> bool:
    """
    Checks whether a specific individual game is an introduction or informational text,
    even if it appears inside a regular opening chapter (e.g. starting with [%info]).
    """
    if is_header_intro(game.headers):
        return True

    # Check root comment (before move 1)
    first_comment = (game.comment or "").strip()
    if first_comment:
        f_lower = first_comment.lower()
        if "[%info]" in f_lower or "[info]" in f_lower:
            return True
        if re.search(r'(?i)^\s*(\[%info\]?|\[info\]?|info\b|intro\b|introduction\b|einleitung\b|overview\b|information\b)', first_comment):
            return True

    # Check first move comment (e.g. 1. e4 { [%info] ... })
    if game.variations:
        first_node = game.variations[0]
        node_comment = (first_node.comment or "").strip()
        if node_comment:
            n_lower = node_comment.lower()
            if "[%info]" in n_lower or "[info]" in n_lower:
                return True
            if re.search(r'(?i)^\s*(\[%info\]?|\[info\]?|info\b|intro\b|introduction\b|einleitung\b|overview\b|information\b)', node_comment):
                return True

    # Check text-only games (0 moves with comment)
    if not game.variations and first_comment:
        return True

    return False

def is_game_puzzle(game: chess.pgn.Game) -> bool:
    """
    Checks whether a specific individual game is a puzzle/exercise,
    even if it appears inside a regular opening chapter.
    """
    if is_header_puzzle(game.headers):
        return True

    # Check starting comment on root node
    first_comment = game.comment or ""
    if first_comment and re.search(r'(?i)\b(white to play|black to play|find the (best|winning|crushing|tactic)|to play and win)\b', first_comment):
        return True

    return False

def is_game_model(game: chess.pgn.Game) -> bool:
    """Checks whether a specific game is a model/reference game."""
    return is_header_model(game.headers)

def detect_course_side(pgn_path: str, default: str = "w") -> str:
    """
    Infers whether the course is for White ('w') or Black ('b')
    using filename and opening heuristics.
    """
    fname = os.path.basename(pgn_path).lower()
    
    if "for black" in fname or "fuer schwarz" in fname or "für schwarz" in fname:
        return "b"
    if "for white" in fname or "fuer weiss" in fname or "für weiß" in fname:
        return "w"
        
    black_openings = [
        "grünfeld", "grunfeld", "french", "französisch", "caro-kann", "sicilian", "sizilianisch", 
        "benko", "tarrasch", "king's indian", "königsindisch", "nimzo", "slav", "slawisch", "pirc", "dragon"
    ]
    
    if "1.e4 e5" in fname or "1.d4 d5" in fname:
        return "b"
        
    if re.search(r'1\.[ed]4\b', fname) and not re.search(r'1\.[ed]4\s+[ed]5', fname):
        return "w"
        
    for bo in black_openings:
        if bo in fname:
            return "b"
            
    return default

def find_cover_image(folder_path: str) -> Optional[str]:
    """Finds a cover image (cover.png, cover.jpg, etc.) in the given directory."""
    if not os.path.isdir(folder_path):
        return None
    for f in os.listdir(folder_path):
        f_lower = f.lower()
        if f_lower.startswith("cover.") and f_lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
            return os.path.join(folder_path, f)
    return None

def analyze_course_pgns(pgn_paths: List[str]) -> CourseAnalysisResult:
    """
    Scans one or multiple PGN files to detect chapters, games, suggested name, color,
    and classifies every chapter and game into its default target.
    """
    if not pgn_paths:
        raise ValueError("No PGN files provided.")

    valid_paths = [p for p in pgn_paths if os.path.exists(p)]
    if not valid_paths:
        raise FileNotFoundError(f"None of the PGN files exist: {pgn_paths}")

    suggested_repo_name = suggest_course_name_from_paths(valid_paths)
    suggested_color = detect_course_side(valid_paths[0])

    cover_image_path = None
    for p in valid_paths:
        cov = find_cover_image(os.path.dirname(p))
        if cov:
            cover_image_path = cov
            break

    chapters_dict: Dict[str, CourseChapterInfo] = {}
    total_games = 0

    for p in valid_paths:
        with open(p, "r", encoding="utf-8", errors="replace") as fp:
            reader = SanitizedPGNReader(fp)
            while True:
                game = chess.pgn.read_game(reader)
                if game is None:
                    break
                game_idx = total_games
                total_games += 1
                headers = game.headers
                chapter_name = headers.get("Black", "").strip() or headers.get("Event", "Default Chapter").strip()
                white_title = headers.get("White", "").strip() or f"Line {total_games}"
                eco = headers.get("ECO", "").strip()
                fen = headers.get("FEN", "").strip()

                is_puz = is_game_puzzle(game)
                is_mod = is_game_model(game)
                is_intr = is_game_intro(game)

                if chapter_name not in chapters_dict:
                    category = classify_chapter(chapter_name)
                    chapters_dict[chapter_name] = CourseChapterInfo(
                        name=chapter_name,
                        game_count=0,
                        sample_titles=[],
                        target_type=category,
                        games=[]
                    )
                
                info = chapters_dict[chapter_name]
                info.game_count += 1
                if len(info.sample_titles) < 3 and white_title:
                    info.sample_titles.append(white_title)

                # Check for embedded puzzles / model games / introductions
                if info.target_type != CATEGORY_TACTICS and is_puz:
                    info.embedded_puzzles += 1
                    game_target = CATEGORY_TACTICS
                elif info.target_type != CATEGORY_MODEL and is_mod:
                    info.embedded_models += 1
                    game_target = CATEGORY_MODEL
                elif info.target_type != CATEGORY_INTRO and is_intr:
                    info.embedded_intros += 1
                    game_target = CATEGORY_INTRO
                else:
                    game_target = info.target_type

                game_info = CourseGameInfo(
                    game_id=game_idx,
                    file_path=p,
                    title=white_title,
                    chapter_name=chapter_name,
                    eco=eco,
                    fen=fen,
                    is_puzzle=is_puz,
                    is_model=is_mod,
                    is_intro=is_intr,
                    target_type=game_target
                )
                info.games.append(game_info)

    # Sort chapters: Quickstarter first, then main chapters, motives, tactics, model, intro, ignore
    order_map = {
        CATEGORY_LEVEL_1: 0,
        CATEGORY_LEVEL_2: 1,
        CATEGORY_MOTIVES: 2,
        CATEGORY_TACTICS: 3,
        CATEGORY_MODEL: 4,
        CATEGORY_INTRO: 5,
        CATEGORY_IGNORE: 6
    }
    sorted_chapters = sorted(chapters_dict.values(), key=lambda c: (order_map.get(c.target_type, 9), natural_sort_key(c.name)))

    category_counts = {
        CATEGORY_LEVEL_1: 0,
        CATEGORY_LEVEL_2: 0,
        CATEGORY_MOTIVES: 0,
        CATEGORY_TACTICS: 0,
        CATEGORY_MODEL: 0,
        CATEGORY_INTRO: 0,
        CATEGORY_IGNORE: 0,
    }
    for c in sorted_chapters:
        for g in c.games:
            category_counts[g.target_type] = category_counts.get(g.target_type, 0) + 1

    suggested_elo = "high"
    combined_text = (suggested_repo_name + " " + " ".join(valid_paths)).lower()
    if re.search(r'\b(master|masters|gm|grandmaster)\b', combined_text):
        suggested_elo = "masters"
    elif re.search(r'\b(club|verein)\b', combined_text):
        suggested_elo = "mid"
    elif re.search(r'\b(hobby|beginner|anf[äa]nger|starter)\b', combined_text):
        suggested_elo = "low"

    return CourseAnalysisResult(
        pgn_paths=valid_paths,
        suggested_repo_name=suggested_repo_name,
        suggested_color=suggested_color,
        suggested_elo=suggested_elo,
        total_games=total_games,
        chapters=sorted_chapters,
        category_counts=category_counts,
        cover_image_path=cover_image_path
    )

def analyze_course_pgn(pgn_path: str) -> CourseAnalysisResult:
    """Convenience wrapper for analyzing a single PGN file."""
    return analyze_course_pgns([pgn_path])

def execute_course_import(
    plan: CourseImportPlan, 
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> CourseImportResult:
    """
    Executes the full automated course import across one or multiple PGN files:
    1. Sets up the repertoire folder, database, default levels, and assets.
    2. Copies cover image if available.
    3. Streams through PGN games:
       - Individual puzzles / Tactics chapters -> Tactics/Tactics.pgn
       - Individual model games / Reference chapters -> Model Games.pgn
       - Level 1 & Level 2 -> SQLite positions & moves with appropriate levels
       - Intro -> Skipped
    4. Performs bulk database saves and health check.
    """
    repo_name = plan.repo_name.strip()
    if not repo_name:
        return CourseImportResult(success=False, message="Repertoire name cannot be empty.")

    paths_to_import = plan.pgn_paths or ([plan.pgn_path] if plan.pgn_path else [])
    paths_to_import = [p for p in paths_to_import if os.path.exists(p)]
    if not paths_to_import:
        return CourseImportResult(success=False, message="No valid PGN files to import.")

    db_path = get_repertoire_db_path(repo_name)
    repo_dir = os.path.dirname(db_path)
    is_new_db = not os.path.exists(db_path)

    # Safety backup if updating an existing repertoire
    if not is_new_db:
        try:
            from opening_fenix.core.services.backup_service import create_repertoire_backup
            create_repertoire_backup(repo_name, trigger_type="pre_course_import_safety")
        except Exception:
            pass

    if progress_callback:
        progress_callback(5, tr_ui("course_import.status_preparing", "Vorbereitung und Datenbank initialisieren..."))

    # 1. Initialize repertoire folder & default assets
    initialize_repertoire_assets(repo_dir)

    # 2. Copy cover image if present
    if plan.cover_image_path and os.path.exists(plan.cover_image_path):
        try:
            ext = os.path.splitext(plan.cover_image_path)[1].lower() or ".png"
            target_cover = os.path.join(repo_dir, f"cover{ext}")
            if not os.path.exists(target_cover):
                shutil.copy2(plan.cover_image_path, target_cover)
                logger.info(f"CourseImport: Copied cover image to {target_cover}")
        except Exception as e:
            logger.warning(f"CourseImport: Could not copy cover image: {e}")

    # 3. Setup Database and Metadata
    db = DatabaseManager(db_path)
    session = db.get_session()

    tactics_dir = os.path.join(repo_dir, "Tactics")
    os.makedirs(tactics_dir, exist_ok=True)
    tactics_pgn_path = os.path.join(tactics_dir, "Tactics.pgn")
    model_pgn_path = os.path.join(repo_dir, "Model Games.pgn")
    motives_pgn_path = os.path.join(repo_dir, "Typical Motives.pgn")
    intro_pgn_path = os.path.join(repo_dir, "Introductions from pgn import.pgn")

    tactics_games_count = 0
    model_games_count = 0
    motives_games_count = 0
    intro_games_saved = 0
    ignored_games_count = 0
    level_1_moves_count = 0
    level_2_moves_count = 0
    embedded_puzzles_count = 0
    embedded_models_count = 0
    embedded_intros_count = 0

    try:
        chosen_elo = plan.elo or "high"
        if is_new_db:
            start_board = chess.Board()
            start_fen = " ".join(start_board.fen().split(" ")[:4])
            if not session.query(Position).filter_by(fen=start_fen).first():
                session.add(Position(fen=start_fen))
            set_meta(session, "name", repo_name)
            set_meta(session, "repertoire_display_name", repo_name)
            set_meta(session, "color", plan.side)
            set_meta(session, "comment_language", plan.target_lang)
            set_meta(session, "elo", chosen_elo)
            set_meta(session, "lichess_elo", chosen_elo)
            session.commit()
        else:
            set_meta(session, "elo", chosen_elo)
            set_meta(session, "lichess_elo", chosen_elo)
            session.commit()

        # Ensure default 3 levels exist
        lang = plan.target_lang if plan.target_lang and plan.target_lang != "auto" else "de"
        lvl_names = {
            "de": ["Grundlagen", "Tiefe Theorie", "Nachschlagewerk und Erklärungen"],
            "en": ["Basics", "Deep Theory", "Reference and Explanations"]
        }.get(lang, ["Grundlagen", "Tiefe Theorie", "Nachschlagewerk und Erklärungen"])

        for order, name in enumerate(lvl_names, 1):
            if not session.query(RepertoireLevel).filter_by(order=order).first():
                session.add(RepertoireLevel(name=name, order=order, target_elo=1500))
        session.commit()

        # 4. Cache positions and moves for bulk loading
        pos_cache = {p.fen: p.id for p in session.query(Position.fen, Position.id).all()}
        move_cache = {(m.from_position_id, m.uci): (m.id, m.nag) for m in session.query(Move.from_position_id, Move.uci, Move.id, Move.nag).all()}
        rep_move_cache = {rm.move_id: rm.level for rm in session.query(RepertoireMove.move_id, RepertoireMove.level).all()}

        max_pos_id = max(pos_cache.values()) if pos_cache else 0
        max_move_id = max(m_id for m_id, _ in move_cache.values()) if move_cache else 0

        new_positions_to_insert = {}
        new_moves_to_insert = []
        new_rep_moves_to_insert = []
        moves_to_update_nag = {}
        comments_to_append = {}

        tactics_buffer = io.StringIO()
        model_buffer = io.StringIO()
        motives_buffer = io.StringIO()
        intro_buffer = io.StringIO()

        total_bytes = sum(os.path.getsize(p) for p in paths_to_import)
        processed_bytes = 0
        game_idx = 0

        if progress_callback:
            progress_callback(15, tr_ui("course_import.status_processing_games", "Verarbeite Partien, Varianten und Puzzles..."))

        # 5. Fast Streaming Pass over all PGN files
        for p_idx, pgn_file in enumerate(paths_to_import):
            file_size = os.path.getsize(pgn_file)
            with open(pgn_file, "r", encoding="utf-8", errors="replace") as fp:
                reader = SanitizedPGNReader(fp)

                while True:
                    game = chess.pgn.read_game(reader)
                    if game is None:
                        break
                    
                    cur_game_id = game_idx
                    game_idx += 1
                    if progress_callback and total_bytes > 0 and game_idx % 20 == 0:
                        cur_tell = processed_bytes + reader.tell()
                        pct = 15 + int((cur_tell / total_bytes) * 65)
                        progress_callback(min(80, pct), tr_ui("course_import.status_importing_pct", "Importiere Partie {idx}...", idx=game_idx))

                    # Identify chapter & default target
                    ch_name = game.headers.get("Black", "").strip() or game.headers.get("Event", "").strip()
                    ch_target = plan.chapter_targets.get(ch_name, classify_chapter(ch_name))

                    # Resolve effective target: explicit game override takes precedence
                    if cur_game_id in plan.game_targets:
                        target = plan.game_targets[cur_game_id]
                    else:
                        if ch_target not in (CATEGORY_TACTICS, CATEGORY_MODEL, CATEGORY_INTRO, CATEGORY_IGNORE, CATEGORY_MOTIVES):
                            if is_game_puzzle(game):
                                target = CATEGORY_TACTICS
                                embedded_puzzles_count += 1
                            elif is_game_model(game):
                                target = CATEGORY_MODEL
                                embedded_models_count += 1
                            elif is_game_intro(game):
                                target = CATEGORY_INTRO
                                embedded_intros_count += 1
                            else:
                                target = ch_target
                        else:
                            target = ch_target

                    # Route according to target
                    if target == CATEGORY_IGNORE:
                        ignored_games_count += 1
                        continue
                    elif target == CATEGORY_INTRO:
                        intro_buffer.write(str(game) + "\n\n")
                        intro_games_saved += 1
                        continue
                    elif target == CATEGORY_MOTIVES:
                        motives_buffer.write(str(game) + "\n\n")
                        motives_games_count += 1
                        continue
                    elif target == CATEGORY_TACTICS:
                        tactics_buffer.write(str(game) + "\n\n")
                        tactics_games_count += 1
                        continue
                    elif target == CATEGORY_MODEL:
                        model_buffer.write(str(game) + "\n\n")
                        model_games_count += 1
                        continue

                    # Must be LEVEL_1 or LEVEL_2
                    level_order = 1 if target == CATEGORY_LEVEL_1 else 2

                    # Parse game tree into moves & positions
                    node_stack = []
                    initial_board = game.board()
                    for node in reversed(game.variations):
                        node_stack.append((node, initial_board.copy()))

                    while node_stack:
                        current_node, board = node_stack.pop()
                        move = current_node.move
                        from_fen = " ".join(board.fen().split(" ")[:4])

                        try:
                            board.push(move)
                        except Exception:
                            continue

                        to_fen = " ".join(board.fen().split(" ")[:4])

                        from_pos_id = pos_cache.get(from_fen)
                        if not from_pos_id:
                            max_pos_id += 1
                            from_pos_id = max_pos_id
                            pos_cache[from_fen] = from_pos_id
                            new_positions_to_insert[from_fen] = Position(id=from_pos_id, fen=from_fen)

                        to_pos_id = pos_cache.get(to_fen)
                        if not to_pos_id:
                            max_pos_id += 1
                            to_pos_id = max_pos_id
                            pos_cache[to_fen] = to_pos_id
                            new_positions_to_insert[to_fen] = Position(id=to_pos_id, fen=to_fen)

                        if current_node.comment:
                            c_lang = plan.target_lang if plan.target_lang and plan.target_lang != "auto" else "de"
                            if to_fen in comments_to_append:
                                comments_to_append[to_fen] = combine_comments(comments_to_append[to_fen], current_node.comment, default_lang=c_lang)
                            else:
                                comments_to_append[to_fen] = combine_comments("", current_node.comment, default_lang=c_lang)

                        incoming_nag = next(iter(current_node.nags), 0)
                        move_san = current_node.san()
                        uci_str = normalize_castling_uci(move.uci(), move_san)
                        move_entry = move_cache.get((from_pos_id, uci_str))

                        if not move_entry:
                            max_move_id += 1
                            move_id = max_move_id
                            move_cache[(from_pos_id, uci_str)] = (move_id, incoming_nag)
                            new_moves_to_insert.append(
                                Move(id=move_id, from_position_id=from_pos_id, to_position_id=to_pos_id, uci=uci_str, san=move_san, nag=incoming_nag)
                            )
                        else:
                            move_id, existing_nag = move_entry
                            if incoming_nag != 0 and existing_nag != incoming_nag:
                                moves_to_update_nag[move_id] = incoming_nag
                                move_cache[(from_pos_id, uci_str)] = (move_id, incoming_nag)

                        # Level priority: Level 1 has higher priority than Level 2
                        if move_id not in rep_move_cache:
                            rep_move_cache[move_id] = level_order
                            new_rep_moves_to_insert.append(RepertoireMove(move_id=move_id, level=level_order))
                            if level_order == 1:
                                level_1_moves_count += 1
                            else:
                                level_2_moves_count += 1
                        elif level_order < rep_move_cache[move_id]:
                            rep_move_cache[move_id] = level_order
                            existing_rm = session.query(RepertoireMove).filter_by(move_id=move_id).first()
                            if existing_rm:
                                existing_rm.level = level_order
                                level_1_moves_count += 1
                                if level_2_moves_count > 0:
                                    level_2_moves_count -= 1

                        for var in reversed(current_node.variations):
                            node_stack.append((var, board.copy()))

            processed_bytes += file_size

        # 6. Write out extracted assets (Tactics, Model Games, Typical Motives, Introductions)
        if progress_callback:
            progress_callback(82, tr_ui("course_import.status_writing_assets", "Speichere Taktiken und Musterpartien..."))

        if tactics_games_count > 0:
            with open(tactics_pgn_path, "a", encoding="utf-8") as f_tac:
                f_tac.write(tactics_buffer.getvalue())

        if model_games_count > 0:
            with open(model_pgn_path, "a", encoding="utf-8") as f_mod:
                f_mod.write(model_buffer.getvalue())

        if motives_games_count > 0:
            with open(motives_pgn_path, "a", encoding="utf-8") as f_mot:
                f_mot.write(motives_buffer.getvalue())

        if intro_games_saved > 0:
            with open(intro_pgn_path, "a", encoding="utf-8") as f_intro:
                f_intro.write(intro_buffer.getvalue())

        # 7. Bulk save objects to SQLite
        if progress_callback:
            progress_callback(88, tr_ui("course_import.status_saving_db", "Speichere Varianten in die Datenbank..."))

        if new_positions_to_insert:
            session.bulk_save_objects(list(new_positions_to_insert.values()))
        if new_moves_to_insert:
            session.bulk_save_objects(new_moves_to_insert)
        if new_rep_moves_to_insert:
            session.bulk_save_objects(new_rep_moves_to_insert)
        if moves_to_update_nag:
            for m_id, n in moves_to_update_nag.items():
                session.query(Move).filter_by(id=m_id).update({'nag': n})

        # 8. Save comments
        if comments_to_append:
            c_lang = plan.target_lang if plan.target_lang and plan.target_lang != "auto" else "de"
            fens = list(comments_to_append.keys())
            for i in range(0, len(fens), 900):
                chunk = fens[i:i + 900]
                positions = session.query(Position).filter(Position.fen.in_(chunk)).all()
                for pos in positions:
                    pos.comment = combine_comments(pos.comment, comments_to_append[pos.fen], default_lang=c_lang)

        # 9. Health repair
        if progress_callback:
            progress_callback(95, tr_ui("course_import.status_health_check", "Führe Konsistenzprüfung durch..."))

        repair_repertoire_health(session, fast=True)

        set_meta(session, "ana_cache_count", "-1")
        set_meta(session, "cov_cache_count", "-1")
        session.commit()

        if progress_callback:
            progress_callback(100, tr_ui("course_import.status_done", "Fertiggestellt!"))

        tac_text = f"{tactics_games_count} Puzzles"
        if embedded_puzzles_count > 0:
            tac_text += f" ({tr_ui('course_import.success_embedded_puz', 'davon {count} aus Kapiteln extrahiert', count=embedded_puzzles_count)})"

        mod_text = f"{model_games_count} Partien"
        if embedded_models_count > 0:
            mod_text += f" ({tr_ui('course_import.success_embedded_mod', 'davon {count} aus Kapiteln extrahiert', count=embedded_models_count)})"

        intro_text = f"{intro_games_saved} Partien"
        if embedded_intros_count > 0:
            intro_text += f" ({tr_ui('course_import.success_embedded_intro', 'davon {count} aus Kapiteln extrahiert', count=embedded_intros_count)})"

        msg = tr_ui(
            "course_import.success_summary",
            "Kurs erfolgreich importiert!\n\n"
            "• Level 1 (Grundlagen): {l1} Züge\n"
            "• Level 2 (Tiefe Theorie): {l2} Züge\n"
            "• Taktikübungen: {tac} in Tactics.pgn\n"
            "• Musterpartien: {mod} in Model Games.pgn\n"
            "• Typische Motive: {mot} Partien in Typical Motives.pgn\n"
            "• Einleitungen: {intro} in Introductions from pgn import.pgn",
            l1=level_1_moves_count,
            l2=level_2_moves_count,
            tac=tac_text,
            mod=mod_text,
            mot=motives_games_count,
            intro=intro_text
        )

        return CourseImportResult(
            success=True,
            message=msg,
            repo_name=repo_name,
            level_1_moves=level_1_moves_count,
            level_2_moves=level_2_moves_count,
            tactics_games=tactics_games_count,
            model_games=model_games_count,
            motives_games=motives_games_count,
            intro_games_saved=intro_games_saved,
            intro_games_skipped=intro_games_saved,
            ignored_games=ignored_games_count,
            embedded_puzzles=embedded_puzzles_count,
            embedded_models=embedded_models_count,
            embedded_intros=embedded_intros_count
        )

    except Exception as e:
        session.rollback()
        import traceback
        logger.error(f"CourseImport failed: {traceback.format_exc()}")
        return CourseImportResult(
            success=False,
            message=tr_ui("course_import.error_failed", "Fehler beim Kurs-Import: {error}", error=str(e)),
            repo_name=repo_name
        )
    finally:
        session.close()
        db.close()
