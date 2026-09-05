import os
import json
import datetime
import pytest
from unittest.mock import MagicMock
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt

from opening_fenix.core.services.training_service import (
    TrainingManager, DEFAULT_BOX_INTERVALS, parse_interval_delta
)
from opening_fenix.core.db.models import Position, Move, RepertoireMove, RepertoireLevel, TrainingData, Base
from opening_fenix.core.db.database import DatabaseManager
from opening_fenix.gui.dialogs.settings_dialog import SettingsDialog


class MockRepertoireManager:
    def __init__(self, repo_name="TestRepo", color="w"):
        self.active_repertoire_name = repo_name
        self.repo_session = None
        self.priority_cache = {}
        self.core = MagicMock()
        self._color = color

    def get_all_repertoires(self):
        return [self.active_repertoire_name] if self.active_repertoire_name else []

    def get_repertoire_color(self):
        return self._color

    def get_level_info(self, level_order):
        info = MagicMock()
        info.target_elo = 1500
        return info

    def _ensure_priority_cache(self):
        pass


class MockMainWindow(QWidget):
    def __init__(self, profile_name="test_profile", repo_name="TestRepo"):
        super().__init__()
        self.profile_name = profile_name
        self.repertoire_manager = MockRepertoireManager(repo_name)
        self.training_manager = TrainingManager(profile_name, self.repertoire_manager)
        self.session_review_count = 0
        self.training_mode = 'due'
        self._had_alternate_attempt = False


# ==========================================================================
# 1. SPACED REPETITION & INTERVAL UNIT TESTS
# =========================================================================

def test_parse_interval_delta():
    """Test parse_interval_delta with various units and boundary values."""
    assert parse_interval_delta(5, "minutes") == datetime.timedelta(minutes=5)
    assert parse_interval_delta(24, "hours") == datetime.timedelta(hours=24)
    assert parse_interval_delta(3, "days") == datetime.timedelta(days=3)
    assert parse_interval_delta(2, "months") == datetime.timedelta(days=60)
    # Zero or negative should clamp to 1
    assert parse_interval_delta(-5, "minutes") == datetime.timedelta(minutes=1)


def test_standard_interval_preset(mock_user_dir):
    """Test standard 7-box Leitner intervals."""
    tm = TrainingManager("prof_std", MockRepertoireManager())
    tm.set_setting("interval_preset", "standard")
    
    assert tm.get_box_interval(1) == datetime.timedelta(minutes=5)
    assert tm.get_box_interval(2) == datetime.timedelta(days=1)
    assert tm.get_box_interval(3) == datetime.timedelta(days=3)
    assert tm.get_box_interval(4) == datetime.timedelta(days=9)
    assert tm.get_box_interval(5) == datetime.timedelta(days=21)
    assert tm.get_box_interval(6) == datetime.timedelta(days=63)
    assert tm.get_box_interval(7) == datetime.timedelta(days=180)


def test_relaxed_interval_preset(mock_user_dir):
    """Test relaxed (long-term) intervals."""
    tm = TrainingManager("prof_rel", MockRepertoireManager())
    tm.set_setting("interval_preset", "relaxed")
    
    assert tm.get_box_interval(1) == datetime.timedelta(minutes=10)
    assert tm.get_box_interval(2) == datetime.timedelta(days=2)
    assert tm.get_box_interval(3) == datetime.timedelta(days=7)
    assert tm.get_box_interval(4) == datetime.timedelta(days=20)
    assert tm.get_box_interval(5) == datetime.timedelta(days=60)
    assert tm.get_box_interval(6) == datetime.timedelta(days=180)
    assert tm.get_box_interval(7) == datetime.timedelta(days=365)


def test_custom_interval_preset(mock_user_dir):
    """Test custom user-defined intervals."""
    tm = TrainingManager("prof_cust", MockRepertoireManager())
    tm.set_setting("interval_preset", "custom")
    tm.set_setting("custom_intervals", {
        "1": {"value": 15, "unit": "minutes"},
        "2": {"value": 6, "unit": "hours"},
        "3": {"value": 5, "unit": "days"},
        "4": {"value": 14, "unit": "days"},
        "5": {"value": 1, "unit": "months"},
        "6": {"value": 3, "unit": "months"},
        "7": {"value": 1, "unit": "months"}
    })
    
    assert tm.get_box_interval(1) == datetime.timedelta(minutes=15)
    assert tm.get_box_interval(2) == datetime.timedelta(hours=6)
    assert tm.get_box_interval(3) == datetime.timedelta(days=5)
    assert tm.get_box_interval(4) == datetime.timedelta(days=14)
    assert tm.get_box_interval(5) == datetime.timedelta(days=30)
    assert tm.get_box_interval(6) == datetime.timedelta(days=90)


def test_profile_independence_for_settings(mock_user_dir):
    """Test that settings are strictly profile-dependent and isolated."""
    repo_mgr = MockRepertoireManager()
    tm_alice = TrainingManager("Alice", repo_mgr)
    tm_bob = TrainingManager("Bob", repo_mgr)
    
    tm_alice.set_setting("interval_preset", "relaxed")
    tm_alice.set_setting("alternate_move_policy", "keep_box")
    tm_alice.set_setting("queue_priority_order", "priority_first")
    
    tm_bob.set_setting("interval_preset", "standard")
    tm_bob.set_setting("alternate_move_policy", "mistake")
    tm_bob.set_setting("queue_priority_order", "box_first")
    
    # Reload from disk
    tm_alice_reloaded = TrainingManager("Alice", repo_mgr)
    tm_bob_reloaded = TrainingManager("Bob", repo_mgr)
    
    assert tm_alice_reloaded.get_setting("interval_preset") == "relaxed"
    assert tm_alice_reloaded.get_setting("alternate_move_policy") == "keep_box"
    assert tm_alice_reloaded.get_setting("queue_priority_order") == "priority_first"
    
    assert tm_bob_reloaded.get_setting("interval_preset") == "standard"
    assert tm_bob_reloaded.get_setting("alternate_move_policy") == "mistake"
    assert tm_bob_reloaded.get_setting("queue_priority_order") == "box_first"


# =========================================================================
# 2. ALTERNATE GOOD MOVES POLICY TESTS
# ========================================================================

def test_alternate_move_policy_no_penalty(mock_user_dir):
    """Test 'no_penalty' policy: playing an alternate move then correct move advances box."""
    repo_mgr = MockRepertoireManager()
    tm = TrainingManager("prof_alt1", repo_mgr)
    tm.set_setting("alternate_move_policy", "no_penalty")
    
    p = Position(id=1, fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQKq e3 0 1")
    m = Move(id=10, from_position_id=1, to_position_id=2, uci="e7e5", san="e5", priority_score=0.9)
    tm._pos_cache = {1: p}
    tm._move_by_id_cache = {10: m}
    tm._rep_move_cache = {10: MagicMock(level=1)}
    
    # Initial success from box 0 -> box 1
    tm.register_success(10, True, had_alternate_attempt=True, was_new=True)
    td = tm.user_session.query(TrainingData).filter_by(move_uci="e7e5").first()
    assert td.box == 1
    assert td.streak == 1
    
    # Next success from box 1 with had_alternate_attempt=True -> box 2 (advances because no_penalty)
    tm.register_success(10, True, had_alternate_attempt=True, was_new=False)
    td = tm.user_session.query(TrainingData).filter_by(move_uci="e7e5").first()
    assert td.box == 2
    assert td.streak == 2


def test_alternate_move_policy_keep_box(mock_user_dir):
    """Test 'keep_box' policy: playing an alternate move refreshes interval but does not advance box."""
    repo_mgr = MockRepertoireManager()
    tm = TrainingManager("prof_alt2", repo_mgr)
    tm.set_setting("alternate_move_policy", "keep_box")
    
    p = Position(id=1, fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQKq e3 0 1")
    m = Move(id=10, from_position_id=1, to_position_id=2, uci="e7e5", san="e5", priority_score=0.9)
    tm._pos_cache = {1: p}
    tm._move_by_id_cache = {10: m}
    tm._rep_move_cache = {10: MagicMock(level=1)}
    
    # First learn -> box 1
    tm.register_success(10, True, had_alternate_attempt=False, was_new=True)
    td = tm.user_session.query(TrainingData).filter_by(move_uci="e7e5").first()
    assert td.box == 1
    
    # Review with alternate attempt first -> stays in box 1
    tm.register_success(10, True, had_alternate_attempt=True, was_new=False)
    td = tm.user_session.query(TrainingData).filter_by(move_uci="e7e5").first()
    assert td.box == 1 # Stays at box 1!
    assert td.streak == 2 # Streak increments
    
    # Review without alternate attempt -> advances to box 2
    tm.register_success(10, True, had_alternate_attempt=False, was_new=False)
    td = tm.user_session.query(TrainingData).filter_by(move_uci="e7e5").first()
    assert td.box == 2 # Now advances!


def test_alternate_move_policy_mistake(mock_user_dir):
    """Test 'mistake' policy: mistake resets box to 1 and streak to 0."""
    repo_mgr = MockRepertoireManager()
    tm = TrainingManager("prof_alt3", repo_mgr)
    tm.set_setting("alternate_move_policy", "mistake")
    
    p = Position(id=1, fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
    m = Move(id=10, from_position_id=1, to_position_id=2, uci="e7e5", san="e5", priority_score=0.9)
    tm._pos_cache = {1: p}
    tm._move_by_id_cache = {10: m}
    tm._rep_move_cache = {10: MagicMock(level=1)}
    
    # Graduate up to Box 3
    for _ in range(3):
        tm.register_success(10, True, had_alternate_attempt=False)
    td = tm.user_session.query(TrainingData).filter_by(move_uci="e7e5").first()
    assert td.box == 3
    
    # Register failure / mistake
    tm.register_success(10, False)
    td = tm.user_session.query(TrainingData).filter_by(move_uci="e7e5").first()
    assert td.box == 1
    assert td.streak == 0


# ========================================================================
# 3. QUEUE PRIORITY SORTING TESTS
# ========================================================================

def test_queue_priority_order_box_first(mock_user_dir):
    """Test queue sorting when queue_priority_order is 'box_first'."""
    repo_mgr = MockRepertoireManager()
    tm = TrainingManager("prof_sort1", repo_mgr)
    tm.set_setting("queue_priority_order", "box_first")
    
    td1 = TrainingData(fen="fen1", move_uci="e2e4", box=2, next_due=datetime.datetime.now() - datetime.timedelta(hours=1))
    td2 = TrainingData(fen="fen2", move_uci="d2d4", box=1, next_due=datetime.datetime.now() - datetime.timedelta(hours=1))
    td3 = TrainingData(fen="fen3", move_uci="c2c4", box=1, next_due=datetime.datetime.now() - datetime.timedelta(hours=1))
    
    repo_mgr.priority_cache = {
        ("fen1", "e2e4"): 0.99,
        ("fen2", "d2d4"): 0.50,
        ("fen3", "c2c4"): 0.80
    }
    
    due_items = [td1, td2, td3]
    sort_order = tm.get_setting("queue_priority_order") or "box_first"
    if sort_order == "priority_first":
        due_items.sort(key=lambda x: (-(repo_mgr.priority_cache.get((x.fen, x.move_uci)) or 0.0), x.box))
    else:
        due_items.sort(key=lambda x: (x.box, -(repo_mgr.priority_cache.get((x.fen, x.move_uci)) or 0.0)))
        
    assert due_items[0] == td3 # Box 1, prio 0.80
    assert due_items[1] == td2 # Box 1, prio 0.50
    assert due_items[2] == td1 # Box 2, prio 0.99


def test_queue_priority_order_priority_first(mock_user_dir):
    """Test queue sorting when queue_priority_order is 'priority_first'."""
    repo_mgr = MockRepertoireManager()
    tm = TrainingManager("prof_sort2", repo_mgr)
    tm.set_setting("queue_priority_order", "priority_first")
    
    td1 = TrainingData(fen="fen1", move_uci="e2e4", box=2, next_due=datetime.datetime.now() - datetime.timedelta(hours=1))
    td2 = TrainingData(fen="fen2", move_uci="d2d4", box=1, next_due=datetime.datetime.now() - datetime.timedelta(hours=1))
    td3 = TrainingData(fen="fen3", move_uci="c2c4", box=1, next_due=datetime.datetime.now() - datetime.timedelta(hours=1))
    
    repo_mgr.priority_cache = {
        ("fen1", "e2e4"): 0.99,
        ("fen2", "d2d4"): 0.50,
        ("fen3", "c2c4"): 0.80
    }
    
    due_items = [td1, td2, td3]
    sort_order = tm.get_setting("queue_priority_order") or "box_first"
    if sort_order == "priority_first":
        due_items.sort(key=lambda x: (-(repo_mgr.priority_cache.get((x.fen, x.move_uci)) or 0.0), x.box))
    else:
        due_items.sort(key=lambda x: (x.box, -(repo_mgr.priority_cache.get((x.fen, x.move_uci)) or 0.0)))
        
    assert due_items[0] == td1 # prio 0.99 (Box 2)
    assert due_items[1] == td3 # prio 0.80 (Box 1)
    assert due_items[2] == td2 # prio 0.50 (Box 1)


# ========================================================================
# 4. DAILY & SESSION LIMITS UNIT TESTS
# ========================================================================

def test_daily_new_cards_counter(mock_user_dir):
    """Test tracking of new cards trained today."""
    tm = TrainingManager("prof_limits1", MockRepertoireManager())
    assert tm.get_today_new_cards_count() == 0
    
    tm.record_new_card_trained()
    assert tm.get_today_new_cards_count() == 1
    
    tm.record_new_card_trained()
    assert tm.get_today_new_cards_count() == 2
    
    tm_reloaded = TrainingManager("prof_limits1", MockRepertoireManager())
    assert tm_reloaded.get_today_new_cards_count() == 2


def test_main_window_limit_detection(mock_user_dir):
    """Test limit detection helper on MainWindow."""
    win = MockMainWindow(profile_name="prof_limit_win")
    
    win.training_manager.set_setting("max_new_cards_per_day", 0)
    win.training_manager.set_setting("max_reviews_per_session", 0)
    
    from opening_fenix.gui.main_window import MainWindow
    is_reached = MainWindow._is_training_limit_reached(win)
    assert is_reached is False
    
    win.training_mode = 'new'
    win.training_manager.set_setting("max_new_cards_per_day", 5)
    assert MainWindow._is_training_limit_reached(win) is False
    for _ in range(5):
        win.training_manager.record_new_card_trained()
    assert MainWindow._is_training_limit_reached(win) is True
    
    win.training_mode = 'due'
    win.training_manager.set_setting("max_reviews_per_session", 10)
    win.session_review_count = 9
    assert MainWindow._is_training_limit_reached(win) is False
    win.session_review_count = 10
    assert MainWindow._is_training_limit_reached(win) is True


# ========================================================================
# 5. SETTINGS DIALOG UI & INTERACTION TESTS (PyQt6 / qtbot)
# ========================================================================

def test_settings_dialog_training_behavior_ui(qtbot, mock_user_dir):
    """Test full UI rendering and interactive changes on the Training Behavior page."""
    win = MockMainWindow(profile_name="prof_ui_test")
    dlg = SettingsDialog(win)
    qtbot.addWidget(dlg)
    
    assert dlg.sidebar.count() == 5
    assert "Trainings-Verhalten" in dlg.sidebar.item(1).text() or "Training Behavior" in dlg.sidebar.item(1).text()
    
    dlg.sidebar.setCurrentRow(1)
    assert dlg.pages.currentIndex() == 1
    
    # 1. Interval Presets
    dlg.combo_interval_preset.setCurrentIndex(0)
    assert dlg.combo_interval_preset.currentData() == "standard"
    assert dlg.box_spinboxes[1].isEnabled() is False
    assert dlg.box_spinboxes[1].value() == 5
    assert dlg.box_unit_combos[1].currentData() == "minutes"
    
    dlg.combo_interval_preset.setCurrentIndex(1)
    assert dlg.combo_interval_preset.currentData() == "relaxed"
    assert dlg.box_spinboxes[1].isEnabled() is False
    assert dlg.box_spinboxes[1].value() == 10
    assert dlg.box_spinboxes[7].value() == 365
    
    dlg.combo_interval_preset.setCurrentIndex(2)
    assert dlg.combo_interval_preset.currentData() == "custom"
    assert dlg.box_spinboxes[1].isEnabled() is True
    assert dlg.box_unit_combos[1].isEnabled() is True
    
    dlg.box_spinboxes[1].setValue(42)
    dlg.box_unit_combos[1].setCurrentIndex(dlg.box_unit_combos[1].findData("hours"))
    
    custom_saved = win.training_manager.get_setting("custom_intervals")
    assert custom_saved["1"]["value"] == 42
    assert custom_saved["1"]["unit"] == "hours"
    
    # 2. Alternate Move Policy
    dlg.combo_alt_policy.setCurrentIndex(dlg.combo_alt_policy.findData("keep_box"))
    assert win.training_manager.get_setting("alternate_move_policy") == "keep_box"
    
    dlg.combo_alt_policy.setCurrentIndex(dlg.combo_alt_policy.findData("mistake"))
    assert win.training_manager.get_setting("alternate_move_policy") == "mistake"
    
    # 3. Queue Priority Order
    dlg.combo_prio_order.setCurrentIndex(dlg.combo_prio_order.findData("priority_first"))
    assert win.training_manager.get_setting("queue_priority_order") == "priority_first"
    
    dlg.combo_prio_order.setCurrentIndex(dlg.combo_prio_order.findData("box_first"))
    assert win.training_manager.get_setting("queue_priority_order") == "box_first"
    
    # 4. Limits
    dlg.spin_max_new.setValue(25)
    assert win.training_manager.get_setting("max_new_cards_per_day") == 25
    
    dlg.spin_max_reviews.setValue(50)
    assert win.training_manager.get_setting("max_reviews_per_session") == 50
    
    dlg.chk_limit_after_var.setChecked(False)
    assert win.training_manager.get_setting("enforce_limit_after_variation") is False
    dlg.chk_limit_after_var.setChecked(True)
    assert win.training_manager.get_setting("enforce_limit_after_variation") is True
    
    # 5. Flow Delay
    dlg.spin_delay.setValue(350)
    assert win.training_manager.get_setting("auto_delay") == 350
