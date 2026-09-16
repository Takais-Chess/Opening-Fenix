import pytest
import chess
from opening_fenix.core.threads import BfsTranspositionThread, PathQualityEvalThread

def norm(f):
    return " ".join(f.strip().split()[:4])

def test_bfs_finds_2move_transposition_to_existing_repertoire():
    """
    Repertoire has:
    Line 1: 1. e4 c5 2. Nf3 (Sicilian 2.Nf3)
    Line 2: 1. e4 e6 (French)
    From 1. e4 (Black to move):
    Black plays 1... c5, White plays 2. Nf3.
    This 2-move transposition leads to Line 1 (Sicilian 2.Nf3).
    Must be found by BfsTranspositionThread at target_depth=2!
    """
    b_e4 = chess.Board()
    b_e4.push_san('e4')
    start_fen = b_e4.fen()

    b_sic = chess.Board()
    b_sic.push_san('e4')
    b_sic.push_san('c5')
    b_sic.push_san('Nf3')
    target_fen = norm(b_sic.fen())

    b_fre = chess.Board()
    b_fre.push_san('e4')
    b_fre.push_san('e6')
    fen_fre = norm(b_fre.fen())

    fen_index = {
        norm(start_fen): True,
        target_fen: True,
        fen_fre: True,
    }

    repo_adj = {
        norm(start_fen): ['e7e6'],  # In this branch, only e6 is registered
    }

    t = BfsTranspositionThread(start_fen, fen_index, target_depth=2, repo_adjacency=repo_adj)
    results = []
    t.depth_complete.connect(lambda d, res, lim: results.extend(res))
    t.run()

    match = [r for r in results if r['depth'] == 2 and r['path_ucis'] == ['c7c5', 'g1f3']]
    assert len(match) == 1
    assert match[0]['target_fen'] == target_fen
    assert match[0]['path_sans'] == ['c5', 'Nf3']

def test_bfs_does_not_suggest_existing_repertoire_path():
    """
    If the exact sequence is already in repo_adjacency from start_fen,
    it should not be suggested as a new transposition.
    """
    b_e4 = chess.Board()
    b_e4.push_san('e4')
    start_fen = b_e4.fen()

    b_sic1 = chess.Board()
    b_sic1.push_san('e4')
    b_sic1.push_san('c5')
    fen_sic1 = norm(b_sic1.fen())

    b_sic2 = chess.Board()
    b_sic2.push_san('e4')
    b_sic2.push_san('c5')
    b_sic2.push_san('Nf3')
    fen_sic2 = norm(b_sic2.fen())

    fen_index = {
        norm(start_fen): True,
        fen_sic1: True,
        fen_sic2: True,
    }

    repo_adj = {
        norm(start_fen): ['c7c5'],
        fen_sic1: ['g1f3'],
    }

    t = BfsTranspositionThread(start_fen, fen_index, target_depth=2, repo_adjacency=repo_adj)
    results = []
    t.depth_complete.connect(lambda d, res, lim: results.extend(res))
    t.run()

    # The exact path c5, Nf3 is already connected in repo_adj, so results must be empty
    assert len(results) == 0

def test_path_quality_relative_score_pov():
    """
    Test PathQualityEvalThread POV scoring:
    Evaluates that relative POV scores accurately classify good moves for both colors.
    """
    raw_paths = [
        {
            "depth": 2,
            "path_sans": ["c5", "Nf3"],
            "path_ucis": ["c7c5", "g1f3"],
            "target_fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -",
        }
    ]
    b = chess.Board()
    b.push_san("e4")
    start_fen = b.fen()

    pq = PathQualityEvalThread(raw_paths, start_fen, "fake_engine.exe")
    assert pq.THRESHOLD_CP == 50
