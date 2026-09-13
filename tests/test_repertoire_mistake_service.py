import json
import pytest
import chess
from unittest.mock import MagicMock, patch
from opening_fenix.core.db.models import Position, Move, RepertoireMove
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.utils import get_repertoire_db_path
from opening_fenix.core.services.repertoire_mistake_service import (
    format_score_to_str, audit_repertoire_mistakes
)
from opening_fenix.core.threads import RepertoireMistakeScanThread


def test_format_score_to_str():
    # Regular centipawns
    score_mock = MagicMock()
    score_mock.is_mate.return_value = False
    score_mock.white.return_value.score.return_value = 85
    s_str, cp = format_score_to_str(score_mock)
    assert s_str == "+0.85"
    assert cp == 85

    # Mate score
    score_mate = MagicMock()
    score_mate.is_mate.return_value = True
    score_mate.white.return_value.mate.return_value = 2
    s_str, cp = format_score_to_str(score_mate)
    assert s_str == "M+2"
    assert cp == 10000


@patch("chess.engine.SimpleEngine.popen_uci")
def test_audit_repertoire_mistakes_no_blunder(mock_popen, mock_user_dir, sample_repertoire):
    mock_engine = MagicMock()
    mock_popen.return_value = mock_engine

    # Move is e2e4, and best move is e2e4 (eval +0.30)
    score_obj = MagicMock()
    score_obj.is_mate.return_value = False
    score_obj.white.return_value.score.return_value = 30
    score_obj.relative.score.return_value = 30

    best_move_obj = chess.Move.from_uci("e2e4")
    mock_info = {
        "pv": [best_move_obj],
        "score": score_obj
    }
    mock_engine.analyse.return_value = [mock_info]

    success, msg, mistakes = audit_repertoire_mistakes(
        sample_repertoire,
        engine_path="dummy_stockfish.exe",
        depth=10,
        threads=1,
        threshold_pawns=0.5
    )

    assert success is True
    # Repertoire move was e2e4, best was e2e4 -> loss is 0.0 -> no mistakes (> 0.5 pawns)
    assert len(mistakes) == 0


@patch("chess.engine.SimpleEngine.popen_uci")
def test_audit_repertoire_mistakes_detects_blunder(mock_popen, mock_user_dir, sample_repertoire):
    mock_engine = MagicMock()
    mock_popen.return_value = mock_engine

    # Engine best move is d2d4 (eval +0.80 -> 80 cp relative)
    score_best = MagicMock()
    score_best.is_mate.return_value = False
    score_best.white.return_value.score.return_value = 80
    score_best.relative.score.return_value = 80

    # Repertoire played e2e4 which in this test evaluates to -0.30 (-30 cp relative) -> loss is 110 cp = 1.1 pawns
    score_rep = MagicMock()
    score_rep.is_mate.return_value = False
    score_rep.white.return_value.score.return_value = -30
    score_rep.relative.score.return_value = -30

    best_move_obj = chess.Move.from_uci("d2d4")
    rep_move_obj = chess.Move.from_uci("e2e4")

    # MultiPV returns best move d2d4, and second move e2e4
    mock_info_best = {"pv": [best_move_obj], "score": score_best}
    mock_info_rep = {"pv": [rep_move_obj], "score": score_rep}

    mock_engine.analyse.return_value = [mock_info_best, mock_info_rep]

    found_mistakes = []
    def on_mistake(m):
        found_mistakes.append(m)

    success, msg, mistakes = audit_repertoire_mistakes(
        sample_repertoire,
        engine_path="dummy_stockfish.exe",
        depth=12,
        threads=2,
        threshold_pawns=0.5,
        mistake_callback=on_mistake
    )

    assert success is True
    assert len(mistakes) >= 1
    m = mistakes[0]
    assert m["played_uci"] == "e2e4"
    assert m["best_uci"] == "d2d4"
    assert m["loss_pawns"] == 1.10
    assert len(found_mistakes) == len(mistakes)


@patch("opening_fenix.core.threads.audit_repertoire_mistakes")
def test_repertoire_mistake_scan_thread(mock_audit):
    mock_audit.return_value = (True, "Done", [{"loss_pawns": 0.9}])
    thread = RepertoireMistakeScanThread("TestRepo", 14, 2, "engine.exe", threshold_pawns=0.5)

    results = []
    thread.finished_signal.connect(lambda s, m, lst: results.append((s, m, lst)))
    thread.run()

    assert len(results) == 1
    assert results[0][0] is True
    assert results[0][2][0]["loss_pawns"] == 0.9
