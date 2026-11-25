import json

import chess
import pytest

from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.db.meta_utils import get_meta, set_meta
from opening_fenix.core.db.models import (
    Position, Move, RepertoireMove, LichessData, MovePriority, Metadata
)
from opening_fenix.core.services.priority_service import (
    calculate_priority_scores, calculate_local_priority_scores,
    sync_move_priorities_to_default_elo,
)
from opening_fenix.core.services.lichess_service import delete_lichess_data
from opening_fenix.core.utils import get_repertoire_db_path, parse_elo_list, serialize_elo_list


def _fen4(board):
    return " ".join(board.fen().split(" ")[:4])


def _build_repo(repo_name):
    """Start -e4(user)-> e4 position; opponent replies e5 / c5. Two Elos disagree on popularity."""
    db = DatabaseManager(get_repertoire_db_path(repo_name))
    session = db.get_session()
    session.add(Metadata(key="color", value="w"))

    b0 = chess.Board()
    b1 = chess.Board(); b1.push_san("e4")
    b2 = b1.copy(); b2.push_san("e5")
    b3 = b1.copy(); b3.push_san("c5")
    pos = [Position(fen=_fen4(b)) for b in (b0, b1, b2, b3)]
    session.add_all(pos)
    session.flush()

    m_e4 = Move(from_position_id=pos[0].id, to_position_id=pos[1].id, uci="e2e4", san="e4")
    m_e5 = Move(from_position_id=pos[1].id, to_position_id=pos[2].id, uci="e7e5", san="e5")
    m_c5 = Move(from_position_id=pos[1].id, to_position_id=pos[3].id, uci="c7c5", san="c5")
    session.add_all([m_e4, m_e5, m_c5])
    session.flush()
    session.add(RepertoireMove(move_id=m_e4.id, is_active=True))

    # "mid": e5 dominates. "high": c5 dominates.
    session.add(LichessData(fen=pos[1].fen, elo_range="mid", moves_json=json.dumps(
        {"e7e5": {"total": 900}, "c7c5": {"total": 100}})))
    session.add(LichessData(fen=pos[1].fen, elo_range="high", moves_json=json.dumps(
        {"e7e5": {"total": 200}, "c7c5": {"total": 800}})))
    session.commit()
    ids = {"e5": m_e5.id, "c5": m_c5.id, "e4": m_e4.id}
    return db, session, ids


def test_elo_list_helpers_canonicalize_and_dedupe():
    assert parse_elo_list("high, mid,mid,bogus") == ["mid", "high"]
    assert parse_elo_list(["MASTERS", "low"]) == ["low", "masters"]
    assert parse_elo_list(None) == []
    assert serialize_elo_list(["high", "low"]) == "low,high"


def test_priorities_are_stored_per_elo(mock_user_dir):
    repo = "multi_elo_prio"
    db, session, ids = _build_repo(repo)
    session.close()

    ok, _ = calculate_priority_scores(repo, "mid")
    assert ok
    ok, _ = calculate_priority_scores(repo, "high")
    assert ok

    session = db.get_session()
    mp = {(r.move_id, r.elo_range): r.priority_score for r in session.query(MovePriority).all()}
    assert mp[(ids["e5"], "mid")] == pytest.approx(0.9)
    assert mp[(ids["c5"], "mid")] == pytest.approx(0.1)
    assert mp[(ids["e5"], "high")] == pytest.approx(0.2)
    assert mp[(ids["c5"], "high")] == pytest.approx(0.8)
    session.close()
    db.close()


def test_move_column_follows_only_the_primary_elo(mock_user_dir):
    repo = "multi_elo_primary"
    db, session, ids = _build_repo(repo)
    set_meta(session, "lichess_elo", "mid")
    session.commit()
    session.close()

    calculate_priority_scores(repo, "mid")
    calculate_priority_scores(repo, "high")  # must NOT overwrite Move.priority_score

    session = db.get_session()
    assert session.get(Move, ids["e5"]).priority_score == pytest.approx(0.9)

    # Instant switch of the default: pure copy from move_priorities, no recalculation
    assert sync_move_priorities_to_default_elo(session, "high") is True
    session.commit()
    session.expire_all()
    assert session.get(Move, ids["e5"]).priority_score == pytest.approx(0.2)
    assert session.get(Move, ids["c5"]).priority_score == pytest.approx(0.8)

    # Nothing stored for this Elo -> untouched
    assert sync_move_priorities_to_default_elo(session, "low") is False
    session.close()
    db.close()


def test_local_recalc_refreshes_every_elo_and_keeps_primary_column(mock_user_dir):
    repo = "multi_elo_local"
    db, session, ids = _build_repo(repo)
    set_meta(session, "lichess_elo", "mid")
    set_meta(session, "lichess_elos", "mid,high")
    session.commit()
    session.close()
    calculate_priority_scores(repo, "mid")
    calculate_priority_scores(repo, "high")

    session = db.get_session()
    # Corrupt both Elos' stored values, then recalc locally below the root
    session.query(MovePriority).filter(MovePriority.move_id.in_([ids["e5"], ids["c5"]])).update(
        {MovePriority.priority_score: 0.0}, synchronize_session=False)
    session.query(Move).filter(Move.id.in_([ids["e5"], ids["c5"]])).update(
        {Move.priority_score: 0.0}, synchronize_session=False)
    session.commit()

    e4_pos = session.get(Move, ids["e4"]).to_position_id
    ok, _ = calculate_local_priority_scores(session, e4_pos, "mid")
    assert ok
    session.commit()
    session.expire_all()

    mp = {(r.move_id, r.elo_range): r.priority_score for r in session.query(MovePriority).all()}
    assert mp[(ids["e5"], "mid")] == pytest.approx(0.9)
    assert mp[(ids["e5"], "high")] == pytest.approx(0.2)
    assert mp[(ids["c5"], "high")] == pytest.approx(0.8)
    # Move column restored to primary (mid)
    assert session.get(Move, ids["e5"]).priority_score == pytest.approx(0.9)
    session.close()
    db.close()


def test_delete_one_elo_removes_its_priorities_and_falls_back_primary(mock_user_dir):
    repo = "multi_elo_delete"
    db, session, ids = _build_repo(repo)
    set_meta(session, "lichess_elo", "mid")
    set_meta(session, "lichess_elos", "mid,high")
    session.commit()
    session.close()
    calculate_priority_scores(repo, "mid")
    calculate_priority_scores(repo, "high")

    ok, _ = delete_lichess_data(repo, "mid")
    assert ok

    session = db.get_session()
    assert session.query(MovePriority).filter_by(elo_range="mid").count() == 0
    assert session.query(MovePriority).filter_by(elo_range="high").count() > 0
    assert get_meta(session, "lichess_elos") == "high"
    assert get_meta(session, "lichess_elo") == "high"
    # Move column now mirrors the new primary
    assert session.get(Move, ids["c5"]).priority_score == pytest.approx(0.8)
    session.close()
    db.close()


def test_trainer_switches_elo_instantly_without_graph_rebuild(mock_user_dir, repertoire_manager):
    from opening_fenix.core.services.training_service import TrainingManager

    repo_name = repertoire_manager.active_repertoire_name
    sess = repertoire_manager.repo_session
    moves = sess.query(Move).all()
    assert moves, "sample repertoire should contain moves"
    mv = moves[0]

    # Two Elos with opposite scores for this move; mid is the course default.
    sess.add(MovePriority(move_id=mv.id, elo_range="mid", priority_score=0.25))
    sess.add(MovePriority(move_id=mv.id, elo_range="high", priority_score=0.75))
    set_meta(sess, "lichess_elo", "mid")
    set_meta(sess, "lichess_elos", "mid,high")
    sess.commit()

    tm = TrainingManager(profile_name="TestUser", repertoire_manager=repertoire_manager)
    try:
        assert tm.get_course_lichess_elos(repo_name) == ("mid", ["mid", "high"])
        assert tm.get_active_lichess_elo(repo_name) == "mid"

        tm._ensure_forward_cache()
        assert tm._move_by_id_cache[mv.id].priority_score == pytest.approx(0.25)
        graph_obj = tm._forward_moves_cache  # must survive the switch (no rebuild)

        tm.set_active_lichess_elo("high", repo_name)
        assert tm.get_active_lichess_elo(repo_name) == "high"
        assert tm._move_by_id_cache[mv.id].priority_score == pytest.approx(0.75)
        assert tm._forward_moves_cache is graph_obj

        tm.set_active_lichess_elo("mid", repo_name)
        assert tm._move_by_id_cache[mv.id].priority_score == pytest.approx(0.25)
    finally:
        tm.close()


def test_single_elo_course_is_untouched_by_overlay(mock_user_dir, repertoire_manager):
    from opening_fenix.core.services.training_service import TrainingManager

    sess = repertoire_manager.repo_session
    mv = sess.query(Move).first()
    mv.priority_score = 0.42
    set_meta(sess, "lichess_elo", "high")
    sess.commit()

    tm = TrainingManager(profile_name="TestUser", repertoire_manager=repertoire_manager)
    try:
        repo_name = repertoire_manager.active_repertoire_name
        _default, available = tm.get_course_lichess_elos(repo_name)
        assert len(available) <= 1
        tm._ensure_forward_cache()
        assert tm._move_by_id_cache[mv.id].priority_score == pytest.approx(0.42)
    finally:
        tm.close()


def test_schema_migration_adds_multi_elo_columns(tmp_path):
    import sqlite3
    from opening_fenix.core.db.models import Base, UserBase

    # Legacy repertoire DB: no move_priorities table, old user_version
    legacy = tmp_path / "legacy_repo.db"
    con = sqlite3.connect(legacy)
    con.executescript(
        "CREATE TABLE moves (id INTEGER PRIMARY KEY, from_position_id INT, to_position_id INT, uci TEXT, san TEXT,"
        " priority_score FLOAT, nag INT);"
        "PRAGMA user_version = 2;"
    )
    con.commit(); con.close()
    mgr = DatabaseManager(str(legacy))
    mgr.close()
    con = sqlite3.connect(legacy)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "move_priorities" in tables

    # Legacy user DB: user_repertoire_settings without active_lichess_elo
    user = tmp_path / "legacy_user.db"
    con = sqlite3.connect(user)
    con.executescript(
        "CREATE TABLE user_repertoire_settings (repertoire_name VARCHAR PRIMARY KEY, active_level INT);"
        "PRAGMA user_version = 2;"
    )
    con.commit(); con.close()
    umgr = DatabaseManager(str(user), base=UserBase)
    umgr.close()
    con = sqlite3.connect(user)
    cols = [r[1] for r in con.execute("PRAGMA table_info(user_repertoire_settings)")]
    con.close()
    assert "active_lichess_elo" in cols


def test_get_repertoire_lichess_elos_fast_discovers_partial_or_legacy_data(mock_user_dir):
    from opening_fenix.core.services.repertoire_core_service import get_repertoire_lichess_elos_fast

    repo = "partial_multi_elo"
    db, session, _ids = _build_repo(repo)
    # Simulate a course where metadata only lists one Elo (e.g. partial/cancelled 2nd import)
    # while lichess_data already has rows for both 'mid' and 'high'.
    set_meta(session, "lichess_elo", "mid")
    session.commit()
    session.close()
    db.close()

    default_elo, available = get_repertoire_lichess_elos_fast(repo)
    assert default_elo == "mid"
    assert available == ["mid", "high"]


def test_batch_maintenance_updates_all_elos_for_course(mock_user_dir, monkeypatch):
    from opening_fenix.core.services import maintenance_service

    repo = "batch_multi_elo"
    db, session, ids = _build_repo(repo)
    set_meta(session, "lichess_elo", "mid")
    set_meta(session, "lichess_elos", "mid,high")
    session.commit()
    session.close()
    db.close()

    imported = []

    def fake_run_lichess_import(r_name, elo_cat, **_kwargs):
        imported.append((r_name, elo_cat))
        return True, "ok"

    monkeypatch.setattr(maintenance_service, "run_lichess_import", fake_run_lichess_import)

    orch = maintenance_service.MaintenanceOrchestrator(
        repo_configs=[{"name": repo, "elo": "mid"}],
        tasks={"lichess": True, "stats": True},
        engine_settings={},
        overall_progress_callback=None,
        repo_status_callback=None,
        check_cancel=None,
    )
    ok, _msg = orch.run()
    assert ok
    assert imported == [(repo, "mid"), (repo, "high")]

    db = DatabaseManager(get_repertoire_db_path(repo))
    session = db.get_session()
    mp = {(r.move_id, r.elo_range): r.priority_score for r in session.query(MovePriority).all()}
    assert mp[(ids["e5"], "mid")] == pytest.approx(0.9)
    assert mp[(ids["c5"], "high")] == pytest.approx(0.8)
    assert session.get(Move, ids["e5"]).priority_score == pytest.approx(0.9)
    session.close()
    db.close()

