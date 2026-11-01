import pytest
import os
import json
import io
from unittest.mock import MagicMock, patch
import chess
import chess.pgn
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.services.analysis_service import run_db_analysis, enrich_position
from opening_fenix.core.services.import_service import import_pgn_to_db
from opening_fenix.core.db.models import Position, Move

@pytest.fixture
def creator_backend(mock_user_dir, sample_repertoire):
    """Fixture for CreatorBackend with sample repertoire."""
    backend = CreatorBackend()
    backend.active_repertoire_name = sample_repertoire
    backend.load_repertoire(sample_repertoire)
    return backend

def test_run_db_analysis_empty(creator_backend, tmp_path):
    """Test analysis on a repertoire with no positions needing it."""
    engine_path = str(tmp_path / "mock_engine.exe")
    with open(engine_path, "w") as f: f.write("mock")
    
    with patch("opening_fenix.core.services.analysis_service.chess.engine.SimpleEngine.popen_uci") as mock_popen:
        mock_engine = MagicMock()
        mock_popen.return_value = mock_engine
        
        success, msg = run_db_analysis(creator_backend.active_repertoire_name, engine_path, 10, 1)
        assert success, f"Analysis failed: {msg}"
        msg_l = msg.lower()
        assert "analys" in msg_l or "abgeschlossen" in msg_l or "keine" in msg_l, f"Unexpected message: {msg}"

def test_enrich_position_basic(creator_backend, monkeypatch):
    """Test the enrichment logic which combines Lichess data and engine."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        'moves': [{'uci': 'e2e4', 'san': 'e4', 'white': 10, 'draws': 5, 'black': 5}]
    }).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: mock_response)
    
    with patch("opening_fenix.core.services.analysis_service.chess.engine.SimpleEngine.popen_uci") as mock_popen:
        mock_engine = MagicMock()
        mock_popen.return_value = mock_engine
        mock_engine.analyse.return_value = [{'score': MagicMock(), 'pv': [chess.Move.from_uci("e2e4")]}]
        
        from chess import STARTING_FEN
        clean_fen = " ".join(STARTING_FEN.split()[:4])
        success, msg = enrich_position(creator_backend.active_repertoire_name, clean_fen, "high", "fake_engine.exe", depth=5)
        
        assert success, f"Enrichment failed: {msg}"
        assert "complete" in msg.lower()

def test_creator_diagnostics(creator_backend):
    """Test the diagnostic and repair tools in the backend."""
    report = creator_backend.run_diagnostic()
    assert isinstance(report, dict)
    
    repaired_count = creator_backend.repair_diagnostic_issues()
    assert isinstance(repaired_count, int)

def test_hole_finder_backend(creator_backend, monkeypatch):
    """Test the hole finder logic in the backend."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        'moves': [{'uci': 'e2e4', 'san': 'e4', 'white': 100, 'draws': 50, 'black': 50}]
    }).encode('utf-8')
    mock_response.__enter__.return_value = mock_response
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: mock_response)
    
    from opening_fenix.core.services.hole_finder_service import find_repertoire_holes
    holes = find_repertoire_holes(creator_backend.session, threshold=0.01, elo_range="high")
    assert isinstance(holes, list)

# Batch 1: PGN Import & Export
def test_pgn_export_and_import_service(creator_backend, tmp_path):
    """Test PGN export and import via services."""
    pgn_string = creator_backend.export_pgn()
    assert isinstance(pgn_string, str)
    
    pgn_path = str(tmp_path / "test.pgn")
    with open(pgn_path, "w") as f:
        f.write(pgn_string)
        
    new_repo = "ImportServiceTest"
    success, msg = import_pgn_to_db(pgn_path, new_repo, "w", "Main", 1)
    assert success, f"PGN Import failed: {msg}"
    assert "erfolgreich" in msg.lower()

# Batch 3: Candidate Moves & Position Data
def test_candidate_moves_and_priority(creator_backend):
    """Test candidate move fetching and priority sorting."""
    # The sample_repertoire fixture already has e4 in the DB
    candidates = creator_backend.get_candidate_moves(chess.STARTING_FEN)
    assert len(candidates) >= 1
    # Check if e4 is in candidates
    uci_list = [c['uci'] for c in candidates]
    assert "e2e4" in uci_list

def test_position_data_update(creator_backend):
    """Test updating position metadata (comments, variations)."""
    fen = chess.STARTING_FEN
    creator_backend.update_position_data(fen, "Top level comment", "Sicilian", "French", "Caro-Kann")
    
    data = creator_backend.get_position_data(fen)
    assert data['comment'] == "Top level comment"
    assert data['variation_1'] == "Sicilian"
    
    # Test inherited variations
    child_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    
    # Trigger recursion by renaming variations on start_pos
    creator_backend.update_position_data(fen, "New", "E4-System", "D4", "C4")
    
    child_data = creator_backend.get_position_data(child_fen)
    # The child should see the parent variation if its own is empty
    assert child_data['variation_1'] == "E4-System"

def test_overhaul_stats_and_session(creator_backend):
    """Test the overhaul session tracking and statistics."""
    import datetime
    now = datetime.datetime.now()
    
    # 1. Test session start save/load
    creator_backend.save_overhaul_session_start(now)
    loaded = creator_backend.get_overhaul_session_start()
    assert loaded is not None
    assert (loaded - now).total_seconds() < 1
    
    # 2. Test stats (initially 0/X)
    checked, total = creator_backend.get_overhaul_stats()
    assert checked == 0
    assert total >= 1
    
    # 3. Mark a position reviewed
    fen = chess.STARTING_FEN
    creator_backend.mark_position_reviewed(fen)
    
    checked, total = creator_backend.get_overhaul_stats()
    assert checked == 1
    
    # 4. Filter by level
    checked, total = creator_backend.get_overhaul_stats(level=1)
    # STARTING_FEN is likely level 1 if it's the root of everything
    assert checked == 1
    
    # 5. Reset progress
    creator_backend.reset_overhaul_progress()
    checked, total = creator_backend.get_overhaul_stats()
    assert checked == 0

def test_variation_inheritance_deep(creator_backend):
    """Test that variation names propagate deep into the tree."""
    # Root: Variation A
    #   Child 1: (empty, inherits A)
    #     Leaf: Variation B (overrides A)
    
    root_fen = chess.STARTING_FEN
    child_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -"
    leaf_fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -"
    
    # Build tree in DB if needed (sample_repertoire might not have leaf)
    # But usually sample_repertoire has enough. Let's just use what we have.
    creator_backend.update_position_data(root_fen, "", "A", "", "")
    
    # Check inheritance on child
    data = creator_backend.get_position_data(child_fen)
    assert data['variation_1'] == "A"
    assert data['v1_inherited'] is True
    
    # Override on leaf
    creator_backend.update_position_data(leaf_fen, "", "B", "", "")
    data = creator_backend.get_position_data(leaf_fen)
    assert data['variation_1'] == "B"
    assert data['v1_inherited'] is False

def test_find_nearest_unreviewed(creator_backend, monkeypatch):
    """Test finding the next position to review."""
    # Ensure a 3-deep tree is active
    # start -> e4 -> e5
    # The fixture already has start -> e4 active. Let's make e4 -> e5 active too.
    from opening_fenix.core.db.models import RepertoireMove, Move, Position
    session = creator_backend.session
    m2 = session.query(Move).filter_by(uci="e7e5").first()
    if m2:
        rm2 = RepertoireMove(move_id=m2.id, level=1)
        session.add(rm2)
        session.commit()

    # Mark root reviewed
    root_fen = chess.STARTING_FEN
    creator_backend.mark_position_reviewed(root_fen)
    
    # Find next (should be e4)
    next_fen = creator_backend.find_nearest_unreviewed(root_fen)
    assert next_fen is not None
    assert next_fen != root_fen
    
    # Mark next reviewed (e4)
    creator_backend.mark_position_reviewed(next_fen)
    
    # Find next again (should be e5)
    next_next_fen = creator_backend.find_nearest_unreviewed(next_fen)
    assert next_next_fen is not None
    assert next_next_fen not in [root_fen, next_fen]

def test_diagnostic_repairs_mocked(creator_backend, monkeypatch):
    """Test the diagnostic tool's ability to identify and fix (mocked) issues."""
    from opening_fenix.core.db.models import RepertoireMove, Move
    
    # 1. Create an orphan move (Move exists but no RepertoireMove)
    # This is one of the things repair_diagnostic_issues fixes
    session = creator_backend.session
    # Use a move that doesn't exist yet to avoid UNIQUE constraint error
    orphan_move = Move(from_position_id=1, to_position_id=2, uci="d2d4", san="d4")
    session.add(orphan_move)
    session.commit()
    
    # Run diagnostic (might report gaps)
    report = creator_backend.run_diagnostic()
    assert 'gaps' in report
    
    # Run repair
    repaired = creator_backend.repair_diagnostic_issues()
    # It should at least run without crashing and return a count
    assert isinstance(repaired, int)


def test_analysis_tab_engine_table_improvements(qapp, mock_user_dir, sample_repertoire):
    """Test the improved engine analysis table, responsive columns, in-place updates, and status messages."""
    from opening_fenix.creator.creator_window import CreatorWindow
    from PyQt6.QtCore import Qt
    
    win = CreatorWindow(repertoire_name=sample_repertoire)
    try:
        # Check initial configuration
        assert hasattr(win, 'table_engine')
        assert hasattr(win, 'combo_lines')
        assert win.table_engine.wordWrap() is False
        
        # Test in-place line update
        sample_output = [
            {'score': '+0.25', 'depth': 20, 'pv': 'e4 c5 Nf3 d6', 'first_uci': 'e2e4'},
            {'score': '+0.10', 'depth': 20, 'pv': 'd4 Nf6 c4', 'first_uci': 'd2d4'}
        ]
        win.update_engine_output(sample_output)
        
        assert win.table_engine.rowCount() == 2
        assert win.table_engine.item(0, 0).text() == "+0.25"
        assert win.table_engine.item(0, 1).text() == "20"
        assert win.table_engine.item(0, 2).text() == "e4 c5 Nf3 d6"
        assert win.table_engine.item(0, 2).data(Qt.ItemDataRole.UserRole) == "e2e4"
        
        # Test in-place update without item recreation
        item_ref = win.table_engine.item(0, 0)
        sample_output[0]['score'] = '+0.30'
        win.update_engine_output(sample_output)
        assert win.table_engine.item(0, 0) is item_ref
        assert win.table_engine.item(0, 0).text() == "+0.30"
        
        # Test status message handling (e.g. checkmate / no legal moves)
        win.update_engine_output(["Partieende / Keine legalen Züge"])
        assert win.table_engine.rowCount() == 1
        assert "Partieende" in win.table_engine.item(0, 2).text()
        
        # Test column adjustment
        win.adjust_engine_columns()
        assert win.table_engine.columnWidth(0) > 0
        assert win.table_engine.columnWidth(1) > 0
        
        # Test combo_lines setting propagation
        win.combo_lines.setCurrentText("1")
        assert win.config.get("engine_multipv") == "1"
    finally:
        win.close()
