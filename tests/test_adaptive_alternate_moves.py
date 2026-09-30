import json
import os
import pytest
import chess
from unittest.mock import MagicMock

from opening_fenix.core.db.models import Position
from opening_fenix.core.services.engine_cache_service import EngineCacheService
from opening_fenix.core.services.analysis_service import (
    extract_score_val,
    evaluate_position_alternate_moves,
    update_position_alternate_moves,
)


def test_engine_cache_alternate_moves_and_transposition_separation(tmp_path):
    """
    Verify that EngineCacheService cleanly separates alternate moves data
    from targeted/transposition eval data for the same FEN without cross-contamination.
    """
    db_file = str(tmp_path / "cache_test.db")
    cache = EngineCacheService(db_path=db_file)
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3"

    # 1. Transposition evaluation at depth 25 (checks specific move c7c5)
    transpos_eval = {
        "best_uci": "c7c5",
        "best_score": 25,
        "moves": {"c7c5": 25, "e7e5": 20},
    }
    cache.set_eval_data(fen, depth=25, best_uci="c7c5", eval_data=transpos_eval)

    # Verify transposition eval is stored
    cached_te = cache.get_eval_data(fen, min_depth=25)
    assert cached_te is not None
    assert cached_te["best_uci"] == "c7c5"
    assert cached_te["moves"]["c7c5"] == 25

    # At this point, no alternate moves should be registered as exhaustive
    assert cache.get_alternate_moves(fen, min_depth=18, require_exhaustive=True) is None

    # 2. Store exhaustive alternate moves analysis at depth 18
    alt_moves = ["c7c5", "e7e5", "e7e6", "c7c6"]
    cache.set_alternate_moves(fen, depth=18, good_moves=alt_moves, is_exhaustive=True, best_uci="c7c5")

    # Verify alternate moves are retrieved
    cached_alt = cache.get_alternate_moves(fen, min_depth=18, require_exhaustive=True)
    assert cached_alt is not None
    assert set(cached_alt["good_moves"]) == set(alt_moves)
    assert cached_alt["depth"] == 18
    assert cached_alt["is_exhaustive"] is True

    # 3. Verify that storing alternate moves DID NOT erase or corrupt the transposition data
    cached_te_after = cache.get_eval_data(fen, min_depth=25)
    assert cached_te_after is not None
    assert cached_te_after["best_uci"] == "c7c5"
    assert cached_te_after["moves"]["c7c5"] == 25
    assert cached_te_after["depth"] == 25


def test_engine_cache_non_exhaustive_merges(tmp_path):
    """
    Verify that non-exhaustive alternate move evaluations merge candidates
    and never overwrite an exhaustive evaluation.
    """
    db_file = str(tmp_path / "cache_merge_test.db")
    cache = EngineCacheService(db_path=db_file)
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6"

    # Store exhaustive list at depth 18
    cache.set_alternate_moves(fen, depth=18, good_moves=["g1f3", "f1c4"], is_exhaustive=True, best_uci="g1f3")

    # Now attempt a non-exhaustive store at depth 20 with only ["g1f3", "d2d4"]
    cache.set_alternate_moves(fen, depth=20, good_moves=["g1f3", "d2d4"], is_exhaustive=False, best_uci="g1f3")

    # The cache should still be marked as exhaustive, and should have merged all moves
    res = cache.get_alternate_moves(fen, min_depth=18, require_exhaustive=True)
    assert res is not None
    assert "f1c4" in res["good_moves"]
    assert "d2d4" in res["good_moves"]
    assert "g1f3" in res["good_moves"]


def test_evaluate_position_adaptive_multipv_early_cutoff():
    """
    Verify that if the 3rd move drops > 50 cp below the best move,
    the search recognizes the cutoff immediately and stops at MultiPV 3.
    """
    board = chess.Board()
    calls = []

    def mock_analyse(b, limit, mpv):
        calls.append(mpv)
        # Mock 3 lines: move 1 and 2 are good, move 3 is -60 cp (cutoff)
        m1 = MagicMock(uci=lambda: "e2e4")
        m2 = MagicMock(uci=lambda: "d2d4")
        m3 = MagicMock(uci=lambda: "h2h4")

        s1 = MagicMock(relative=MagicMock(score=lambda mate_score: 30), white=MagicMock(score=lambda mate_score: 30))
        s2 = MagicMock(relative=MagicMock(score=lambda mate_score: 25), white=MagicMock(score=lambda mate_score: 25))
        s3 = MagicMock(relative=MagicMock(score=lambda mate_score: -35), white=MagicMock(score=lambda mate_score: -35))

        return [
            {"pv": [m1], "score": s1},
            {"pv": [m2], "score": s2},
            {"pv": [m3], "score": s3},
        ]

    good_moves, is_exhaustive, best_uci, best_eval = evaluate_position_alternate_moves(
        analyse_func=mock_analyse,
        board=board,
        depth=15,
        repertoire_uci="e2e4"
    )

    # Should have called analyse only once with mpv=3
    assert calls == [3]
    assert is_exhaustive is True
    assert set(good_moves) == {"e2e4", "d2d4"}
    assert "h2h4" not in good_moves
    assert best_uci == "e2e4"


def test_evaluate_position_adaptive_multipv_expands_when_no_cutoff():
    """
    Verify that if all 3 initial lines are good (diff <= 50 cp),
    MultiPV expands dynamically (3 -> 6) to find all good moves.
    """
    board = chess.Board()
    calls = []

    def mock_analyse(b, limit, mpv):
        calls.append(mpv)
        if mpv == 3:
            # 3 lines, all very close (loss <= 10 cp) -> no cutoff
            return [
                {"pv": [MagicMock(uci=lambda: "e2e4")], "score": MagicMock(relative=MagicMock(score=lambda x: 30), white=MagicMock(score=lambda x: 30))},
                {"pv": [MagicMock(uci=lambda: "d2d4")], "score": MagicMock(relative=MagicMock(score=lambda x: 28), white=MagicMock(score=lambda x: 28))},
                {"pv": [MagicMock(uci=lambda: "g1f3")], "score": MagicMock(relative=MagicMock(score=lambda x: 25), white=MagicMock(score=lambda x: 25))},
            ]
        elif mpv == 6:
            # 6 lines: moves 1-4 good, 5-6 drop off > 50 cp
            return [
                {"pv": [MagicMock(uci=lambda: "e2e4")], "score": MagicMock(relative=MagicMock(score=lambda x: 30), white=MagicMock(score=lambda x: 30))},
                {"pv": [MagicMock(uci=lambda: "d2d4")], "score": MagicMock(relative=MagicMock(score=lambda x: 28), white=MagicMock(score=lambda x: 28))},
                {"pv": [MagicMock(uci=lambda: "g1f3")], "score": MagicMock(relative=MagicMock(score=lambda x: 25), white=MagicMock(score=lambda x: 25))},
                {"pv": [MagicMock(uci=lambda: "c2c4")], "score": MagicMock(relative=MagicMock(score=lambda x: 22), white=MagicMock(score=lambda x: 22))},
                {"pv": [MagicMock(uci=lambda: "b2b3")], "score": MagicMock(relative=MagicMock(score=lambda x: -30), white=MagicMock(score=lambda x: -30))},
                {"pv": [MagicMock(uci=lambda: "g2g3")], "score": MagicMock(relative=MagicMock(score=lambda x: -40), white=MagicMock(score=lambda x: -40))},
            ]

    good_moves, is_exhaustive, best_uci, best_eval = evaluate_position_alternate_moves(
        analyse_func=mock_analyse,
        board=board,
        depth=15,
        repertoire_uci="e2e4"
    )

    # Called with 3, then expanded to 6
    assert calls == [3, 6]
    assert is_exhaustive is True
    # Moves 1 to 4 should be recognized as good
    assert set(good_moves) == {"e2e4", "d2d4", "g1f3", "c2c4"}


def test_update_position_alternate_moves_safe_overwrite():
    """
    Verify safe overwrite rule:
    - Exhaustive scan overwrites.
    - Non-exhaustive scan merges without deleting previous good moves.
    - Lower depth does not downgrade higher depth.
    """
    pos = Position(id=1, fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3", analysis_depth=15, good_moves=json.dumps(["c7c5", "e7e5"]))

    # 1. Non-exhaustive scan at depth 20 with only ["c7c5"]
    update_position_alternate_moves(pos, depth=20, good_moves=["c7c5"], is_exhaustive=False)
    # Both "c7c5" and "e7e5" MUST be preserved!
    saved_moves = json.loads(pos.good_moves)
    assert "e7e5" in saved_moves
    assert "c7c5" in saved_moves

    # 2. Exhaustive scan at depth 18 with ["c7c5", "e7e6"]
    update_position_alternate_moves(pos, depth=18, good_moves=["c7c5", "e7e6"], is_exhaustive=True)
    # Now it should be cleanly updated
    saved_moves2 = json.loads(pos.good_moves)
    assert set(saved_moves2) == {"c7c5", "e7e6"}
    assert pos.analysis_depth == 18

    # 3. Lower depth scan (depth 12) should NOT downgrade depth
    update_position_alternate_moves(pos, depth=12, good_moves=["c7c5"], is_exhaustive=True)
    assert pos.analysis_depth == 18


def test_reset_repertoire_engine_analysis(mock_user_dir, sample_repertoire):
    """Verify that reset_repertoire_engine_analysis clears analysis data while keeping moves intact."""
    from opening_fenix.core.services.analysis_service import reset_repertoire_engine_analysis
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.utils import get_repertoire_db_path

    db_path = get_repertoire_db_path(sample_repertoire)
    db = DatabaseManager(db_path)
    session = db.get_session()

    # Set analysis on positions
    positions = session.query(Position).all()
    assert len(positions) > 0
    for p in positions:
        p.analysis_depth = 18
        p.good_moves = json.dumps(["e2e4"])
        p.engine_eval = 25
    session.commit()
    session.close()
    db.close()

    # Reset
    count = reset_repertoire_engine_analysis(sample_repertoire)
    assert count == len(positions)

    # Verify positions are reset
    db = DatabaseManager(db_path)
    session = db.get_session()
    for p in session.query(Position).all():
        assert p.analysis_depth is None
        assert p.good_moves is None
        assert p.engine_eval is None
    session.close()
    db.close()


def test_clear_alternate_moves_cache(tmp_path):
    """Verify that clear_alternate_moves purges alternate moves without deleting transposition data."""
    db_file = str(tmp_path / "cache_clear_test.db")
    cache = EngineCacheService(db_path=db_file)
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3"

    # Store both transposition eval and alternate moves
    cache.set_eval_data(fen, depth=25, best_uci="c7c5", eval_data={"moves": {"c7c5": 25}})
    cache.set_alternate_moves(fen, depth=18, good_moves=["c7c5"], is_exhaustive=True, best_uci="c7c5")

    # Clear alternate moves
    cache.clear_alternate_moves()

    # Alternate moves should be gone
    assert cache.get_alternate_moves(fen, min_depth=18, require_exhaustive=True) is None

    # Transposition eval must still be intact!
    te = cache.get_eval_data(fen, min_depth=25)
    assert te is not None
    assert te["best_uci"] == "c7c5"


def test_evaluate_multipv_exhaustiveness_cutoff_and_non_exhaustive():
    """Verify exhaustiveness rules on completed MultiPV lines."""
    from opening_fenix.core.services.analysis_service import evaluate_multipv_exhaustiveness
    import chess

    board = chess.Board() # 20 legal moves for White

    class MockScore:
        def __init__(self, cp):
            self._cp = cp
        def score(self, *args, **kwargs):
            return self._cp

    class MockPovScore:
        def __init__(self, cp):
            self.relative = MockScore(cp)
            self.white = lambda *args, **kwargs: MockScore(cp)

    # 1. Cutoff: Line 1 (+30), Line 2 (+15), Line 3 (-60) at depth 20 (threshold 30)
    # Line 3 loss = 30 - (-60) = 90 > 30 -> Cutoff achieved!
    lines_with_cutoff = [
        {"pv": [chess.Move.from_uci("e2e4")], "score": MockPovScore(30), "depth": 20},
        {"pv": [chess.Move.from_uci("d2d4")], "score": MockPovScore(15), "depth": 20},
        {"pv": [chess.Move.from_uci("g1f3")], "score": MockPovScore(-60), "depth": 20},
    ]
    good, is_ex, best_uci, best_eval = evaluate_multipv_exhaustiveness(board, 20, lines_with_cutoff)
    assert is_ex is True
    assert set(good) == {"e2e4", "d2d4"}
    assert best_uci == "e2e4"

    # 2. Non-exhaustive: Line 1 (+30), Line 2 (+25), Line 3 (+20)
    # All 3 are good, but 17 moves left unanalyzed -> NOT exhaustive
    lines_no_cutoff = [
        {"pv": [chess.Move.from_uci("e2e4")], "score": MockPovScore(30), "depth": 20},
        {"pv": [chess.Move.from_uci("d2d4")], "score": MockPovScore(25), "depth": 20},
        {"pv": [chess.Move.from_uci("g1f3")], "score": MockPovScore(20), "depth": 20},
    ]
    good_non, is_ex_non, best_uci_non, _ = evaluate_multipv_exhaustiveness(board, 20, lines_no_cutoff)
    assert is_ex_non is False
    assert set(good_non) == {"e2e4", "d2d4", "g1f3"}

    # 3. All legal moves evaluated (e.g., board with only 3 legal moves)
    board_3_moves = chess.Board("8/8/8/8/8/5k2/8/6K1 w - - 0 1")
    assert board_3_moves.legal_moves.count() == 3
    lines_all_moves = [
        {"pv": [chess.Move.from_uci("g1h2")], "score": MockPovScore(0), "depth": 20},
        {"pv": [chess.Move.from_uci("g1h1")], "score": MockPovScore(-10), "depth": 20},
        {"pv": [chess.Move.from_uci("g1f1")], "score": MockPovScore(-20), "depth": 20},
    ]
    good_all, is_ex_all, _, _ = evaluate_multipv_exhaustiveness(board_3_moves, 20, lines_all_moves)
    assert is_ex_all is True


def test_creator_backend_engine_analysis_finished_rules(sample_repertoire, mock_user_dir):
    """
    Verify CreatorBackend.handle_engine_analysis_finished:
    - If exhaustive: updates pos.good_moves and pos.analysis_depth.
    - If non-exhaustive: leaves pos.good_moves and pos.analysis_depth UNTOUCHED.
    - update_position_analysis does NOT modify analysis_depth.
    """
    from opening_fenix.creator.creator_window import CreatorBackend
    from opening_fenix.core.db.database import DatabaseManager
    from opening_fenix.core.utils import get_repertoire_db_path
    import chess

    backend = CreatorBackend()
    backend.load_repertoire(sample_repertoire)

    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3"
    pos = backend.session.query(Position).first()
    assert pos is not None
    fen = pos.fen

    # Reset initial state
    pos.analysis_depth = 12
    pos.good_moves = json.dumps(["c7c5"])
    pos.engine_eval = 20
    backend.session.commit()

    class MockScore:
        def __init__(self, cp):
            self._cp = cp
        def score(self, *args, **kwargs):
            return self._cp

    class MockPovScore:
        def __init__(self, cp):
            self.relative = MockScore(cp)
            self.white = lambda *args, **kwargs: MockScore(cp)

    # 1. Intermediate update_position_analysis should NOT touch analysis_depth or good_moves
    backend.update_position_analysis(fen, depth=16, eval_val=35)
    backend.session.refresh(pos)
    assert pos.analysis_depth == 12  # Must NOT be modified to 16!
    assert pos.good_moves == json.dumps(["c7c5"])
    assert pos.engine_eval == 35

    # 2. Non-exhaustive engine analysis completed at depth 20 (all 3 lines good)
    b = chess.Board(fen)
    legal = list(b.legal_moves)
    assert len(legal) > 3

    lines_non_ex = [
        {"pv": [legal[0]], "score": MockPovScore(35), "depth": 20},
        {"pv": [legal[1]], "score": MockPovScore(30), "depth": 20},
        {"pv": [legal[2]], "score": MockPovScore(25), "depth": 20},
    ]
    res_non_ex = backend.handle_engine_analysis_finished(fen, depth=20, lines=lines_non_ex)
    assert res_non_ex is False
    backend.session.refresh(pos)
    # MUST NOT CHANGE: good_moves and analysis_depth must remain 100% untouched!
    assert pos.analysis_depth == 12
    assert pos.good_moves == json.dumps(["c7c5"])

    # 3. Exhaustive engine analysis completed at depth 20 (3rd line drops > threshold worse)
    lines_ex = [
        {"pv": [legal[0]], "score": MockPovScore(35), "depth": 20},
        {"pv": [legal[1]], "score": MockPovScore(25), "depth": 20},
        {"pv": [legal[2]], "score": MockPovScore(-80), "depth": 20}, # 115 cp loss > 30 cp -> cutoff
    ]
    res_ex = backend.handle_engine_analysis_finished(fen, depth=20, lines=lines_ex)
    assert res_ex is True
    backend.session.refresh(pos)
    # MUST BE UPDATED:
    assert pos.analysis_depth == 20
    saved = json.loads(pos.good_moves)
    assert legal[0].uci() in saved
    assert legal[1].uci() in saved
    assert legal[2].uci() not in saved

    backend.close()

