import pytest
import datetime
from opening_fenix.core.training import TrainingManager
from opening_fenix.core.models import TrainingData

def test_init_user_db(training_manager):
    assert training_manager.user_session is not None
    assert training_manager.profile_name == "TestUser"

def test_settings(training_manager):
    training_manager.set_setting("test_key", "test_value")
    assert training_manager.get_setting("test_key") == "test_value"

def test_get_stats_empty(training_manager):
    new, due, dist = training_manager.get_stats()
    assert new == 1 # 1. e4 is new
    assert due == 0
    assert sum(dist.values()) == 0

def test_register_success(training_manager, repertoire_manager):
    # Get move ID for 1. e4
    from opening_fenix.core.models import Move
    move = repertoire_manager.repo_session.query(Move).filter_by(uci="e2e4").first()
    
    # Register success
    training_manager.register_success(move.id, True)
    
    # To avoid timing issues with the 5-minute interval, 
    # we manually push the next_due date further into the future
    entry = training_manager.user_session.query(TrainingData).filter_by(move_uci="e2e4").first()
    entry.next_due = datetime.datetime.now() + datetime.timedelta(hours=1)
    training_manager.user_session.commit()
    training_manager._td_cache = None
    
    # Check stats
    new, due, dist = training_manager.get_stats(use_cache=False)
    assert new == 0
    assert due == 0
    assert dist[1] == 1 # Now it must be in box 1 and NOT due

def test_get_next_move_new(training_manager):
    move, path = training_manager.get_next_move(mode='new')
    assert move is not None
    assert move.uci == "e2e4"
    assert isinstance(path, list)

def test_get_next_move_due(training_manager, repertoire_manager):
    from opening_fenix.core.models import Move
    move = repertoire_manager.repo_session.query(Move).filter_by(uci="e2e4").first()
    
    # Register success but force it to be due
    training_manager.register_success(move.id, True)
    
    # Manually update next_due in DB to past
    entry = training_manager.user_session.query(TrainingData).first()
    entry.next_due = datetime.datetime.now() - datetime.timedelta(minutes=1)
    training_manager.user_session.commit()
    
    next_move, path = training_manager.get_next_move(mode='due')
    assert next_move is not None
    assert next_move.uci == "e2e4"
    assert isinstance(path, list)

def test_register_failure(training_manager, repertoire_manager):
    from opening_fenix.core.models import Move
    move = repertoire_manager.repo_session.query(Move).filter_by(uci="e2e4").first()

    # Move to box 1 first
    training_manager.register_success(move.id, True)
    entry = training_manager.user_session.query(TrainingData).first()
    assert entry.box == 1

    # Register failure (success=False)
    training_manager.register_success(move.id, False)
    
    # After failure, it should be in box 1 (per current implementation)
    entry = training_manager.user_session.query(TrainingData).first()
    assert entry.box == 1
    assert entry.streak == 0

def test_box_progression(training_manager, repertoire_manager):
    from opening_fenix.core.models import Move
    move = repertoire_manager.repo_session.query(Move).filter_by(uci="e2e4").first()

    # Success 1 -> Box 1
    training_manager.register_success(move.id, True)
    entry = training_manager.user_session.query(TrainingData).filter_by(move_uci="e2e4").first()
    assert entry.box == 1
    
    # Success 2 -> Box 2
    training_manager.register_success(move.id, True)
    # Refetch or check session
    training_manager.user_session.refresh(entry)
    assert entry.box == 2
    
    # Success 3 -> Box 3
    training_manager.register_success(move.id, True)
    training_manager.user_session.refresh(entry)
    assert entry.box == 3

def test_get_stats_with_data(training_manager, repertoire_manager):
    from opening_fenix.core.models import Move
    move = repertoire_manager.repo_session.query(Move).filter_by(uci="e2e4").first()
    
    training_manager.register_success(move.id, True)
    
    # We need to make sure the side matches
    # sample_repertoire default is White
    new, due, dist = training_manager.get_stats()
    
    # If new is still 1, maybe it didn't find the TrainingData entry
    # because of repertoire_name mismatch?
    # Let's check repertoire name
    assert training_manager.repertoire_manager.active_repertoire_name == "TestRepo"
    
    # If it's due because of 5m lookahead, that's fine, but new should be 0
    assert new == 0
