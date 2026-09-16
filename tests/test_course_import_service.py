import os
import shutil
import pytest
import sqlite3
import chess
import chess.pgn

from opening_fenix.core.services.course_import_service import (
    classify_chapter,
    detect_course_side,
    sanitize_repertoire_name,
    SanitizedPGNReader,
    analyze_course_pgn,
    analyze_course_pgns,
    is_game_puzzle,
    is_game_model,
    is_header_intro,
    is_game_intro,
    execute_course_import,
    CourseImportPlan,
    CATEGORY_LEVEL_1,
    CATEGORY_LEVEL_2,
    CATEGORY_TACTICS,
    CATEGORY_MODEL,
    CATEGORY_INTRO
)
from opening_fenix.core.utils import get_user_dir, get_repertoire_db_path

def test_classify_chapter():
    # Level 1 (Quickstarter)
    assert classify_chapter("Quickstarter Guide") == CATEGORY_LEVEL_1
    assert classify_chapter("Quickstarter Guide Part 1: Sicilian Defence") == CATEGORY_LEVEL_1
    assert classify_chapter("Schnellstarter Ruy Lopez") == CATEGORY_LEVEL_1
    assert classify_chapter("Introduction and Quickstarter Guide") == CATEGORY_LEVEL_1

    # Intro
    assert classify_chapter("Introduction") == CATEGORY_INTRO
    assert classify_chapter("Einleitung") == CATEGORY_INTRO
    assert classify_chapter("1) French Overview") == CATEGORY_INTRO
    assert classify_chapter("4. Italian 6...a6 − Introduction & Overview") == CATEGORY_INTRO

    # Tactics
    assert classify_chapter("Training Exercises") == CATEGORY_TACTICS
    assert classify_chapter("8) Theme based tactics drills") == CATEGORY_TACTICS
    assert classify_chapter("Jobava London Sub-Sidelines: Tactics") == CATEGORY_TACTICS

    # Model Games
    assert classify_chapter("Model Games") == CATEGORY_MODEL
    assert classify_chapter("Reference Games") == CATEGORY_MODEL
    assert classify_chapter("Musterpartien") == CATEGORY_MODEL

    # Level 2 (Default / Deep theory)
    assert classify_chapter("Chapter 10: The Dragon") == CATEGORY_LEVEL_2
    assert classify_chapter("1. Najdorf 5.Nc3 a6 6.Rg1") == CATEGORY_LEVEL_2
    assert classify_chapter("25) Italienisch 5.d4 Vollzentrum") == CATEGORY_LEVEL_2

def test_detect_course_side():
    assert detect_course_side("Lifetime Repertoires Sethuraman's 1.e4 - Part 2.pgn") == "w"
    assert detect_course_side("Lifetime Repertoires Peter Svidler's Grünfeld - Part 1.pgn") == "b"
    assert detect_course_side("Attacking Repertoire for Club Players for Black.pgn") == "b"
    assert detect_course_side("1.e4 e5 - Dreckige Offene Spiele.pgn") == "b"
    assert detect_course_side("1.d4 Ben Finegold.pgn") == "w"

def test_sanitize_repertoire_name():
    raw = "Lifetime Repertoires: Peter Svidler's Grünfeld / Part 1 *?"
    clean = sanitize_repertoire_name(raw)
    assert ":" not in clean
    assert "/" not in clean
    assert "*" not in clean
    assert "?" not in clean
    assert "Lifetime Repertoires - Peter Svidler's Grünfeld Part 1" == clean

def test_sanitized_pgn_reader():
    import io
    bad_pgn = '[Event "Test"]\n[White "A"]\n[Black "B"]\n[FEN ""]\n[Result "*"]\n\n1. e4 e5 *\n'
    reader = SanitizedPGNReader(io.StringIO(bad_pgn))
    game = chess.pgn.read_game(reader)
    assert game is not None
    assert game.headers["White"] == "A"
    assert len(list(game.mainline_moves())) == 2

@pytest.fixture
def temp_course_env(tmp_path, monkeypatch):
    monkeypatch.setattr("opening_fenix.core.utils.get_user_dir", lambda: str(tmp_path))
    monkeypatch.setattr("opening_fenix.core.data_tools.get_user_dir", lambda: str(tmp_path))
    monkeypatch.setattr("opening_fenix.core.services.course_import_service.get_user_dir", lambda: str(tmp_path))
    monkeypatch.setattr("opening_fenix.core.services.import_service.get_user_dir", lambda: str(tmp_path))
    return tmp_path

def test_end_to_end_course_import(temp_course_env):
    # Create synthetic multi-chapter course PGN
    pgn_content = """
[Event "Sample Course"]
[White "Intro"]
[Black "Introduction"]
[Result "*"]
1. e4 {Text intro} *

[Event "Sample Course"]
[White "Sicilian Basics"]
[Black "Quickstarter Guide"]
[Result "*"]
1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 *

[Event "Sample Course"]
[White "Najdorf Deep Line"]
[Black "Chapter 1: Najdorf"]
[Result "*"]
1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 6. Bg5 e6 7. f4 Qb6 8. Qd2 Qxb2 *

[Event "Sample Course"]
[White "Tactics 1"]
[Black "Training Exercises"]
[FEN "r1bqkb1r/pp2pppp/3p4/1P2nP2/5B2/2N5/1PP3PP/R2QKB1R w KQkq - 0 13"]
[Result "*"]
1. Bxe5 dxe5 2. Qxd8+ Kxd8 *

[Event "Sample Course"]
[White "Carlsen vs Anand"]
[Black "Model Games"]
[FEN ""]
[Result "*"]
1. e4 c5 2. Nf3 *
"""
    pgn_path = os.path.join(temp_course_env, "Test Course.pgn")
    with open(pgn_path, "w", encoding="utf-8") as f:
        f.write(pgn_content)

    # 1. Test Analysis
    analysis = analyze_course_pgn(pgn_path)
    assert analysis.suggested_repo_name == "Test Course"
    assert analysis.total_games == 5
    assert analysis.category_counts[CATEGORY_LEVEL_1] == 1
    assert analysis.category_counts[CATEGORY_LEVEL_2] == 1
    assert analysis.category_counts[CATEGORY_TACTICS] == 1
    assert analysis.category_counts[CATEGORY_MODEL] == 1
    assert analysis.category_counts[CATEGORY_INTRO] == 1

    # 2. Test Execution
    plan = CourseImportPlan(
        pgn_path=pgn_path,
        repo_name="Test Course",
        side="w",
        chapter_targets={c.name: c.target_type for c in analysis.chapters},
        cover_image_path=None,
        target_lang="de"
    )

    progress_events = []
    def on_progress(pct, msg):
        progress_events.append((pct, msg))

    result = execute_course_import(plan, progress_callback=on_progress)
    assert result.success is True
    assert result.level_1_moves > 0
    assert result.level_2_moves > 0
    assert result.tactics_games == 1
    assert result.model_games == 1
    assert result.intro_games_skipped == 1

    # Verify Tactics/Tactics.pgn exists and has content
    from opening_fenix.core.utils import get_repertoire_dir
    repo_dir = get_repertoire_dir("Test Course")
    tactics_file = os.path.join(repo_dir, "Tactics", "Tactics.pgn")
    assert os.path.exists(tactics_file)
    with open(tactics_file, "r", encoding="utf-8") as f:
        t_content = f.read()
    assert "Training Exercises" in t_content

    # Verify Model Games.pgn exists and has content
    model_file = os.path.join(repo_dir, "Model Games.pgn")
    assert os.path.exists(model_file)
    with open(model_file, "r", encoding="utf-8") as f:
        m_content = f.read()
    assert "Model Games" in m_content

    # Verify Database levels
    db_path = get_repertoire_db_path("Test Course")
    assert os.path.exists(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT level FROM repertoire_moves")
    levels = [r[0] for r in cursor.fetchall()]
    assert 1 in levels
    assert 2 in levels

    cursor.execute("SELECT key, value FROM metadata WHERE key IN ('elo', 'lichess_elo')")
    meta_rows = dict(cursor.fetchall())
    assert meta_rows.get("elo") == "high"
    assert meta_rows.get("lichess_elo") == "high"
    conn.close()


def test_multi_pgn_analysis_and_embedded_puzzles(temp_course_env):
    part1_content = """
[Event "Lifetime Repertoires"]
[White "Part 1 Quickstart"]
[Black "Quickstarter Guide"]
[Result "*"]
1. e4 e5 2. Nf3 Nc6 *

[Event "Lifetime Repertoires"]
[White "Part 1 Main"]
[Black "Chapter 1: Open Game"]
[Result "*"]
1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 *
"""
    part2_content = """
[Event "Lifetime Repertoires"]
[White "Embedded Puzzle"]
[Black "Chapter 2: Najdorf"]
[FEN "r1bqkb1r/pp2pppp/3p4/1P2nP2/5B2/2N5/1PP3PP/R2QKB1R w KQkq - 0 13"]
[Result "*"]
1. Bxe5 dxe5 2. Qxd8+ Kxd8 *

[Event "Lifetime Repertoires"]
[White "Part 2 Main"]
[Black "Chapter 2: Najdorf"]
[Result "*"]
1. e4 c5 2. Nf3 d6 3. d4 cxd4 *
"""
    p1 = os.path.join(temp_course_env, "Lifetime Repertoires - Part 1.pgn")
    p2 = os.path.join(temp_course_env, "Lifetime Repertoires - Part 2.pgn")
    with open(p1, "w", encoding="utf-8") as f:
        f.write(part1_content)
    with open(p2, "w", encoding="utf-8") as f:
        f.write(part2_content)

    # Test multi-PGN analysis
    analysis = analyze_course_pgns([p1, p2])
    assert analysis.suggested_repo_name == "Lifetime Repertoires"
    assert analysis.total_games == 4
    assert len(analysis.chapters) == 3  # Quickstarter, Chapter 1, Chapter 2
    assert analysis.category_counts[CATEGORY_LEVEL_1] == 1
    assert analysis.category_counts[CATEGORY_LEVEL_2] == 2
    assert analysis.category_counts[CATEGORY_TACTICS] == 1
    ch2 = next(c for c in analysis.chapters if "Chapter 2" in c.name)
    assert ch2.embedded_puzzles == 1

    # Execute and verify embedded puzzle extraction
    plan = CourseImportPlan(
        pgn_path=p1,
        pgn_paths=[p1, p2],
        repo_name="Lifetime Repertoires Multi",
        side="w",
        chapter_targets={c.name: c.target_type for c in analysis.chapters},
        cover_image_path=None,
        target_lang="en"
    )
    result = execute_course_import(plan)
    assert result.success is True
    # The game with non-standard FEN in Chapter 2 must be extracted as a puzzle even though Chapter 2 is Level 2!
    assert result.tactics_games == 1
    assert result.embedded_puzzles == 1
    assert result.level_1_moves > 0
    assert result.level_2_moves > 0


def test_motives_introductions_and_line_overrides(temp_course_env):
    pgn_content = """
[Event "Sicilian Masterclass"]
[White "General Intro"]
[Black "Introduction"]
[Result "*"]
1. e4 {Welcome to Sicilian} *

[Event "Sicilian Masterclass"]
[White "Specific Motive Line"]
[Black "Chapter 1: Sicilian Sacrifices"]
[Result "*"]
1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 6. Nd5 {Nd5 sacrifice theme} *

[Event "Sicilian Masterclass"]
[White "Regular Theory Line"]
[Black "Chapter 1: Sicilian Sacrifices"]
[Result "*"]
1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 6. Be2 e5 *

[Event "Sicilian Masterclass"]
[White "Line To Ignore"]
[Black "Chapter 1: Sicilian Sacrifices"]
[Result "*"]
1. e4 c5 2. a3 *
"""
    pgn_path = os.path.join(temp_course_env, "Sicilian Masterclass.pgn")
    with open(pgn_path, "w", encoding="utf-8") as f:
        f.write(pgn_content)

    analysis = analyze_course_pgns([pgn_path])
    assert analysis.total_games == 4
    
    # Check that games were tracked with CourseGameInfo
    ch1 = next(c for c in analysis.chapters if "Sicilian Sacrifices" in c.name)
    assert len(ch1.games) == 3
    assert ch1.games[0].title == "Specific Motive Line"
    motive_game_id = ch1.games[0].game_id
    ignore_game_id = ch1.games[2].game_id

    # Create plan with individual line overrides:
    # 1. Game 0: Introduction -> intro (writes to Introductions from pgn import.pgn)
    # 2. Game 1: Specific Motive Line -> CATEGORY_MOTIVES (writes to Typical Motives.pgn)
    # 3. Game 2: Regular Theory -> CATEGORY_LEVEL_2 (chapter default)
    # 4. Game 3: Line To Ignore -> CATEGORY_IGNORE (skipped)
    from opening_fenix.core.services.course_import_service import (
        CATEGORY_MOTIVES,
        CATEGORY_IGNORE
    )

    plan = CourseImportPlan(
        pgn_paths=[pgn_path],
        repo_name="Sicilian Masterclass",
        side="w",
        chapter_targets={c.name: c.target_type for c in analysis.chapters},
        game_targets={
            motive_game_id: CATEGORY_MOTIVES,
            ignore_game_id: CATEGORY_IGNORE
        }
    )

    result = execute_course_import(plan)
    assert result.success is True
    assert result.intro_games_saved == 1
    assert result.motives_games == 1
    assert result.ignored_games == 1
    assert result.level_2_moves > 0

    from opening_fenix.core.utils import get_repertoire_dir
    repo_dir = get_repertoire_dir("Sicilian Masterclass")

    # 1. Verify Introductions from pgn import.pgn
    intro_file = os.path.join(repo_dir, "Introductions from pgn import.pgn")
    assert os.path.exists(intro_file)
    with open(intro_file, "r", encoding="utf-8") as f:
        intro_text = f.read()
    assert "General Intro" in intro_text
    assert "Welcome to Sicilian" in intro_text

    # 2. Verify Typical Motives.pgn
    motives_file = os.path.join(repo_dir, "Typical Motives.pgn")
    assert os.path.exists(motives_file)
    with open(motives_file, "r", encoding="utf-8") as f:
        motives_text = f.read()
    assert "Specific Motive Line" in motives_text
    assert "Nd5 sacrifice theme" in motives_text

    # 3. Verify ignored line was neither in motives nor intros
    assert "Line To Ignore" not in intro_text
    assert "Line To Ignore" not in motives_text

def test_course_import_natural_chapter_sorting(tmp_path):
    pgn_content = """[Event "Course"]
[Site "?"]
[Date "2026.01.01"]
[Round "1"]
[White "Line 1"]
[Black "11) Archangel with 7.Nxe5"]
[Result "*"]

1. e4 e5 *

[Event "Course"]
[Site "?"]
[Date "2026.01.01"]
[Round "2"]
[White "Line 2"]
[Black "1) Archangel with 5.Qe2"]
[Result "*"]

1. e4 e5 *

[Event "Course"]
[Site "?"]
[Date "2026.01.01"]
[Round "3"]
[White "Line 3"]
[Black "2) Archangel with 6.c3"]
[Result "*"]

1. e4 e5 *

[Event "Course"]
[Site "?"]
[Date "2026.01.01"]
[Round "4"]
[White "Line 4"]
[Black "Quickstarter Guide"]
[Result "*"]

1. e4 e5 *
"""
    p = tmp_path / "archangel.pgn"
    p.write_text(pgn_content, encoding="utf-8")

    analysis = analyze_course_pgn(str(p))
    chapter_names = [c.name for c in analysis.chapters]
    
    assert chapter_names == [
        "Quickstarter Guide",
        "1) Archangel with 5.Qe2",
        "2) Archangel with 6.c3",
        "11) Archangel with 7.Nxe5"
    ]

def test_is_intro_detection():
    import io

    # 1. Starting root comment with [%info]
    pgn1 = """[Event "Course"]
[White "1.e4 e5"]
[Black "Openings"]

{ [%info] Welcome to the course overview } 1. e4 e5 *
"""
    g1 = chess.pgn.read_game(io.StringIO(pgn1))
    assert is_game_intro(g1) is True

    # 2. Starting root comment with just [%info]
    pgn2 = """[Event "Course"]
[White "1.e4 e5"]
[Black "Openings"]

{ [%info] } 1. e4 e5 *
"""
    g2 = chess.pgn.read_game(io.StringIO(pgn2))
    assert is_game_intro(g2) is True

    # 3. First move comment with [%info]
    pgn3 = """[Event "Course"]
[White "1.e4 e5"]
[Black "Openings"]

1. e4 { [%info] Information about 1.e4 } e5 *
"""
    g3 = chess.pgn.read_game(io.StringIO(pgn3))
    assert is_game_intro(g3) is True

    # 4. White header starting with Info
    pgn4 = """[Event "Course"]
[White "Info: Scotch Game Introduction"]
[Black "Openings"]

1. e4 e5 2. Nf3 Nc6 3. d4 *
"""
    g4 = chess.pgn.read_game(io.StringIO(pgn4))
    assert is_game_intro(g4) is True

    # 5. Header with [%info] tag
    pgn5 = """[Event "Course"]
[White "[%info] 1.e4"]
[Black "Openings"]

1. e4 e5 *
"""
    g5 = chess.pgn.read_game(io.StringIO(pgn5))
    assert is_game_intro(g5) is True

    # 6. Text-only game with 0 moves and a comment
    pgn6 = """[Event "Course"]
[White "Course Introduction"]
[Black "Openings"]

{ In this video and chapter we cover the general ideas } *
"""
    g6 = chess.pgn.read_game(io.StringIO(pgn6))
    assert is_game_intro(g6) is True

    # 7. Regular theory game (should NOT be detected as intro)
    pgn7 = """[Event "Course"]
[White "1. e4 e5 2. Nf3 Nc6"]
[Black "Openings"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 *
"""
    g7 = chess.pgn.read_game(io.StringIO(pgn7))
    assert is_game_intro(g7) is False

def test_classify_chapter_intro_variants():
    assert classify_chapter("Info") == CATEGORY_INTRO
    assert classify_chapter("Infos") == CATEGORY_INTRO
    assert classify_chapter("Information") == CATEGORY_INTRO
    assert classify_chapter("Informationen") == CATEGORY_INTRO
    assert classify_chapter("1. Intro") == CATEGORY_INTRO
    assert classify_chapter("Introduction") == CATEGORY_INTRO
    assert classify_chapter("Überblick und Konzept") == CATEGORY_INTRO
    assert classify_chapter("Ueberblick") == CATEGORY_INTRO
    assert classify_chapter("Vorwort") == CATEGORY_INTRO
    assert classify_chapter("[%info] Course Notes") == CATEGORY_INTRO

def test_embedded_intro_extraction_in_course_import(temp_course_env):
    # Chapter 1 is a normal opening chapter (Level 2), but contains an embedded [%info] game
    pgn_content = """
[Event "Ruy Lopez Masterclass"]
[White "1.e4 e5 Overview"]
[Black "Chapter 1: Open Games"]
[Result "*"]
{ [%info] This line provides an overview of the pawn structures } 1. e4 e5 2. Nf3 Nc6 *

[Event "Ruy Lopez Masterclass"]
[White "Mainline 3.Bb5 a6"]
[Black "Chapter 1: Open Games"]
[Result "*"]
1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 *
"""
    p = os.path.join(temp_course_env, "Ruy Lopez.pgn")
    with open(p, "w", encoding="utf-8") as f:
        f.write(pgn_content)

    # 1. Analyze
    analysis = analyze_course_pgn(p)
    assert analysis.total_games == 2
    assert len(analysis.chapters) == 1
    ch1 = analysis.chapters[0]
    assert ch1.name == "Chapter 1: Open Games"
    assert ch1.target_type == CATEGORY_LEVEL_2
    assert ch1.embedded_intros == 1
    assert ch1.games[0].is_intro is True
    assert ch1.games[0].target_type == CATEGORY_INTRO
    assert ch1.games[1].is_intro is False
    assert ch1.games[1].target_type == CATEGORY_LEVEL_2

    # 2. Execute import
    plan = CourseImportPlan(
        pgn_paths=[p],
        repo_name="Ruy Lopez Intro Test",
        side="w",
        chapter_targets={c.name: c.target_type for c in analysis.chapters}
    )
    result = execute_course_import(plan)
    assert result.success is True
    assert result.embedded_intros == 1
    assert result.intro_games_saved == 1
    assert result.level_2_moves > 0

    # 3. Verify Introductions from pgn import.pgn was created with the [%info] game
    from opening_fenix.core.utils import get_repertoire_dir
    repo_dir = get_repertoire_dir("Ruy Lopez Intro Test")
    intro_file = os.path.join(repo_dir, "Introductions from pgn import.pgn")
    assert os.path.exists(intro_file)
    with open(intro_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "1.e4 e5 Overview" in content
    assert "This line provides an overview" in content



