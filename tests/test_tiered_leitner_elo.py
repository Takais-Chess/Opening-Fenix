import datetime
import pytest
from opening_fenix.core.db.models import (
    Position, Move, RepertoireMove, RepertoireLevel, TrainingData, Base, UserRepertoireSettings
)
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.core.repertoire import RepertoireManager
from opening_fenix.core.training import TrainingManager
from opening_fenix.core.utils import get_repertoire_db_path

@pytest.fixture
def multi_level_repertoire(mock_user_dir):
    """Creates a repertoire with 2 levels: Level 1 (target 1800) and Level 2 (target 2300)."""
    repo_name = "MultiLevelRepo"
    db_path = get_repertoire_db_path(repo_name)
    db = DatabaseManager(db_path, base=Base)
    session = db.get_session()
    
    lvl1 = RepertoireLevel(name="Basics", order=1, target_elo=1800)
    lvl2 = RepertoireLevel(name="Deep", order=2, target_elo=2300)
    session.add_all([lvl1, lvl2])
    
    # Create positions
    p0 = Position(fen="pos_0")
    p1 = Position(fen="pos_1")
    p2 = Position(fen="pos_2")
    p3 = Position(fen="pos_3")
    session.add_all([p0, p1, p2, p3])
    session.flush()
    
    # Moves: m1 and m2 in Level 1; m3 in Level 2
    m1 = Move(from_position_id=p0.id, to_position_id=p1.id, uci="e2e4", san="e4")
    m2 = Move(from_position_id=p1.id, to_position_id=p2.id, uci="e7e5", san="e5")
    m3 = Move(from_position_id=p2.id, to_position_id=p3.id, uci="g1f3", san="Nf3")
    session.add_all([m1, m2, m3])
    session.flush()
    
    rm1 = RepertoireMove(move_id=m1.id, level=1, is_active=True)
    rm2 = RepertoireMove(move_id=m2.id, level=1, is_active=True)
    rm3 = RepertoireMove(move_id=m3.id, level=2, is_active=True)
    session.add_all([rm1, rm2, rm3])
    
    session.commit()
    session.close()
    db.close()
    return repo_name

def test_fresh_repertoire_starts_at_800(mock_user_dir, multi_level_repertoire):
    rm = RepertoireManager()
    rm.set_active_repertoire(multi_level_repertoire)
    tm = TrainingManager(profile_name="TestProfile", repertoire_manager=rm)
    tm.on_repertoire_changed()
    
    elo = tm.get_current_elo()
    assert elo == 800

def test_box5_achieves_target_elo(mock_user_dir, multi_level_repertoire):
    rm = RepertoireManager()
    rm.set_active_repertoire(multi_level_repertoire)
    tm = TrainingManager(profile_name="TestProfile", repertoire_manager=rm)
    tm.on_repertoire_changed()
    tm.set_active_level(1)
    
    now = datetime.datetime.now()
    future = now + datetime.timedelta(days=10)
    
    # Put both Level 1 moves in Box 5 (fresh)
    td1 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_0", move_uci="e2e4", box=5, next_due=future)
    td2 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_1", move_uci="e7e5", box=5, next_due=future)
    tm.user_session.add_all([td1, td2])
    tm.user_session.commit()
    tm._td_cache = None
    
    elo = tm.get_current_elo(use_cache=False)
    # Level 1 target is 1800. Since all Level 1 moves are in Box 5 (100% weight), Elo should be 1800!
    assert elo == 1800

def test_box7_provides_mastery_buffer(mock_user_dir, multi_level_repertoire):
    rm = RepertoireManager()
    rm.set_active_repertoire(multi_level_repertoire)
    tm = TrainingManager(profile_name="TestProfile", repertoire_manager=rm)
    tm.on_repertoire_changed()
    tm.set_active_level(1)
    
    now = datetime.datetime.now()
    future = now + datetime.timedelta(days=30)
    
    # Put both Level 1 moves in Box 7 (weight 1.10)
    td1 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_0", move_uci="e2e4", box=7, next_due=future)
    td2 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_1", move_uci="e7e5", box=7, next_due=future)
    tm.user_session.add_all([td1, td2])
    tm.user_session.commit()
    tm._td_cache = None
    
    elo = tm.get_current_elo(use_cache=False)
    # 800 + (1800 - 800) * 1.10 = 800 + 1100 = 1900
    assert elo == 1900

def test_due_cards_act_two_boxes_down(mock_user_dir, multi_level_repertoire):
    rm = RepertoireManager()
    rm.set_active_repertoire(multi_level_repertoire)
    tm = TrainingManager(profile_name="TestProfile", repertoire_manager=rm)
    tm.on_repertoire_changed()
    tm.set_active_level(1)
    
    now = datetime.datetime.now()
    past = now - datetime.timedelta(days=2) # overdue!
    
    # Both moves are in Box 5, but overdue. They act as Box 3 (weight 0.65)
    td1 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_0", move_uci="e2e4", box=5, next_due=past)
    td2 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_1", move_uci="e7e5", box=5, next_due=past)
    tm.user_session.add_all([td1, td2])
    tm.user_session.commit()
    tm._td_cache = None
    
    elo = tm.get_current_elo(use_cache=False)
    # 800 + (1800 - 800) * 0.65 = 800 + 650 = 1450
    assert elo == 1450

def test_level_switch_no_elo_plunge(mock_user_dir, multi_level_repertoire):
    rm = RepertoireManager()
    rm.set_active_repertoire(multi_level_repertoire)
    tm = TrainingManager(profile_name="TestProfile", repertoire_manager=rm)
    tm.on_repertoire_changed()
    
    now = datetime.datetime.now()
    future = now + datetime.timedelta(days=10)
    
    # Level 1 is fully mastered at Box 5
    td1 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_0", move_uci="e2e4", box=5, next_due=future)
    td2 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_1", move_uci="e7e5", box=5, next_due=future)
    tm.user_session.add_all([td1, td2])
    tm.user_session.commit()
    tm._td_cache = None
    
    tm.set_active_level(1)
    elo_lvl1 = tm.get_current_elo(use_cache=False)
    assert elo_lvl1 == 1800
    
    # Now unlock Level 2! (m3 is unseen, box 0)
    tm.set_active_level(2)
    elo_lvl2 = tm.get_current_elo(use_cache=False)
    
    # Critical test: Switching to Level 2 MUST NOT drop the Elo!
    assert elo_lvl2 == 1800

def test_tiered_level_scaling(mock_user_dir, multi_level_repertoire):
    rm = RepertoireManager()
    rm.set_active_repertoire(multi_level_repertoire)
    tm = TrainingManager(profile_name="TestProfile", repertoire_manager=rm)
    tm.on_repertoire_changed()
    tm.set_active_level(2)
    
    now = datetime.datetime.now()
    future = now + datetime.timedelta(days=10)
    
    # Level 1 at Box 5 (target 1800), Level 2 move (m3) at Box 5 (target 2300)
    td1 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_0", move_uci="e2e4", box=5, next_due=future)
    td2 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_1", move_uci="e7e5", box=5, next_due=future)
    td3 = TrainingData(repertoire_name=multi_level_repertoire, fen="pos_2", move_uci="g1f3", box=5, next_due=future)
    tm.user_session.add_all([td1, td2, td3])
    tm.user_session.commit()
    tm._td_cache = None
    
    elo = tm.get_current_elo(use_cache=False)
    # Both Level 1 (1800) and Level 2 (2300) are 100% mastered -> Elo is exactly 2300!
    assert elo == 2300

def test_get_rating_and_all_ratings(mock_user_dir, multi_level_repertoire):
    rm = RepertoireManager()
    rm.set_active_repertoire(multi_level_repertoire)
    tm = TrainingManager(profile_name="TestProfile", repertoire_manager=rm)
    tm.on_repertoire_changed()
    
    # Calculate Elo to populate cache and DB
    calculated_elo = tm.get_current_elo(use_cache=False)
    
    # Check get_rating_for_repertoire
    rating = tm.get_rating_for_repertoire(multi_level_repertoire)
    assert rating == float(calculated_elo)

    # Check non-existent repertoire falls back to 800.0
    assert tm.get_rating_for_repertoire("NonExistentRepo") == 800.0

    # Check get_ratings_for_all_repertoires
    all_ratings = tm.get_ratings_for_all_repertoires()
    assert multi_level_repertoire in all_ratings
    assert all_ratings[multi_level_repertoire] == float(calculated_elo)

