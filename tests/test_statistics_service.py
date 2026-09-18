import os
import json
import pytest
import chess
from opening_fenix.creator.creator_window import CreatorBackend
from opening_fenix.core.models import Position, Move, RepertoireMove, LichessData, Metadata
from opening_fenix.core.services.statistics_service import calculate_repertoire_statistics, _get_learnability_rating

def clean_fen(fen):
    return " ".join(fen.split(" ")[:4])

def test_learnability_rating():
    compact = _get_learnability_rating(100, 40)
    assert compact["tier"] == "Kompakt"
    assert compact["score"] >= 90

    moderate = _get_learnability_rating(350, 100)
    assert moderate["tier"] == "Moderat"
    assert moderate["score"] == 80

    extensive = _get_learnability_rating(800, 200)
    assert extensive["tier"] == "Umfangreich"
    assert extensive["score"] <= 70

def test_empty_or_missing_repertoire():
    res = calculate_repertoire_statistics("NonExistentRepo12345_XYZ")
    assert res["levels"]["total_positions"] == 0
    assert res["levels"]["level_1"] == 0
    assert len(res["coverage_curve"]) == 0

def test_statistics_with_sample_repertoire(mock_user_dir, sample_repertoire):
    be = CreatorBackend()
    be.load_repertoire(sample_repertoire)
    
    # Run stats calculation on sample repertoire
    stats = calculate_repertoire_statistics(sample_repertoire)
    
    assert "levels" in stats
    assert "total_positions" in stats["levels"]
    assert "scope" in stats
    assert "soundness" in stats
    assert "effectiveness" in stats
    assert "coverage_curve" in stats
    assert isinstance(stats["coverage_curve"], list)

    be.close()

def test_scope_detection_specialized_black(mock_user_dir, sample_repertoire):
    """Test that a Black repertoire responding only to 1.e4 is correctly detected as 'Gegen 1.e4' with 100% Move 1 in-scope coverage."""
    be = CreatorBackend()
    be.load_repertoire(sample_repertoire)
    session = be.session

    # Set metadata color = 'b'
    m_color = session.query(Metadata).filter_by(key="color").first()
    if m_color:
        m_color.value = 'b'
    else:
        session.add(Metadata(key="color", value='b'))

    # Root position
    start_fen = clean_fen(chess.STARTING_FEN)
    root_pos = session.query(Position).filter(Position.fen.like(start_fen + "%")).first()
    if not root_pos:
        root_pos = Position(fen=start_fen)
        session.add(root_pos)
        session.flush()

    # Clear moves and add White 1.e4, Black 1... e5
    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.commit()

    e4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -")
    e4_pos = session.query(Position).filter(Position.fen.like(e4_fen + "%")).first()
    if not e4_pos:
        e4_pos = Position(fen=e4_fen)
        session.add(e4_pos)
        session.flush()

    m_e4 = Move(from_position_id=root_pos.id, to_position_id=e4_pos.id, uci="e2e4", san="e4")
    session.add(m_e4)
    session.flush()
    session.add(RepertoireMove(move_id=m_e4.id, level=1, is_active=True))

    e5_fen = clean_fen("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq -")
    e5_pos = session.query(Position).filter(Position.fen.like(e5_fen + "%")).first()
    if not e5_pos:
        e5_pos = Position(fen=e5_fen)
        session.add(e5_pos)
        session.flush()

    m_e5 = Move(from_position_id=e4_pos.id, to_position_id=e5_pos.id, uci="e7e5", san="e5")
    session.add(m_e5)
    session.flush()
    session.add(RepertoireMove(move_id=m_e5.id, level=1, is_active=True))

    session.commit()

    stats = calculate_repertoire_statistics(sample_repertoire)
    assert stats["scope"]["is_specialized"] is True
    assert "1.e4" in stats["scope"]["name"]
    # Move 1 in-scope coverage should be 100%
    if stats["coverage_curve"]:
        assert stats["coverage_curve"][0]["coverage_pct"] == 100.0

    be.close()

def test_scope_detection_anti_e4(mock_user_dir, sample_repertoire):
    """Test that a Black repertoire covering 1.d4, 1.c4, 1.Nf3 (all moves except 1.e4) is detected as specialized without 1.e4."""
    be = CreatorBackend()
    be.load_repertoire(sample_repertoire)
    session = be.session

    m_color = session.query(Metadata).filter_by(key="color").first()
    if m_color:
        m_color.value = 'b'
    else:
        session.add(Metadata(key="color", value='b'))

    start_fen = clean_fen(chess.STARTING_FEN)
    root_pos = session.query(Position).filter(Position.fen.like(start_fen + "%")).first()
    if not root_pos:
        root_pos = Position(fen=start_fen)
        session.add(root_pos)
        session.flush()

    session.query(RepertoireMove).delete()
    session.query(Move).delete()
    session.commit()

    # Add 1.d4 and 1.c4
    d4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq -")
    d4_pos = Position(fen=d4_fen)
    session.add(d4_pos)
    session.flush()
    m_d4 = Move(from_position_id=root_pos.id, to_position_id=d4_pos.id, uci="d2d4", san="d4")
    session.add(m_d4)
    session.flush()
    session.add(RepertoireMove(move_id=m_d4.id, level=1, is_active=True))

    c4_fen = clean_fen("rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq -")
    c4_pos = Position(fen=c4_fen)
    session.add(c4_pos)
    session.flush()
    m_c4 = Move(from_position_id=root_pos.id, to_position_id=c4_pos.id, uci="c2c4", san="c4")
    session.add(m_c4)
    session.flush()
    session.add(RepertoireMove(move_id=m_c4.id, level=1, is_active=True))

    session.commit()

    stats = calculate_repertoire_statistics(sample_repertoire)
    assert stats["scope"]["is_specialized"] is True
    # Name should indicate it's against 1.d4 & flanks or without 1.e4
    scope_name = stats["scope"]["name"]
    assert "d4" in scope_name or "ohne 1.e4" in scope_name or "without 1.e4" in scope_name

    # Levels list check
    assert "list" in stats["levels"]
    assert len(stats["levels"]["list"]) >= 1
    assert "Level 1 (" in stats["levels"]["list"][0]["display_name"]

    be.close()

def test_statistics_dialog_ui(qtbot, mock_user_dir, sample_repertoire):
    from opening_fenix.gui.dialogs.stats_dialog import RepertoireStatisticsDialog
    dlg = RepertoireStatisticsDialog(repo_name=sample_repertoire)
    qtbot.addWidget(dlg)
    assert "Statistiken" in dlg.windowTitle() or "Statistics" in dlg.windowTitle()
    assert dlg.repo_name == sample_repertoire
    assert hasattr(dlg, "card_eff")
    assert hasattr(dlg, "card_wip")
    assert not hasattr(dlg, "card_snd")
    assert not hasattr(dlg, "card_lrn")
    # Wait briefly for worker to complete
    if dlg.worker:
        dlg.worker.wait(2000)
    dlg.close()
