import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton

from opening_fenix.gui.widgets.repertoire_tabs import RepertoireTabsWidget
from opening_fenix.gui.widgets.training_center import TrainingCenterWidget

def test_repertoire_tabs_widget(qtbot):
    widget = RepertoireTabsWidget()
    qtbot.addWidget(widget)
    
    # Test setting ELO and profile
    widget.set_elo("1850")
    assert "1850" in widget.lbl_elo.text()
    
    widget.set_profile_name("Grandmaster")
    assert widget.btn_profile.text() == "Grandmaster"
    
    widget.set_filter_text("Variation A")
    assert widget.btn_filter.text() == "Variation A"
    
    # Test scroll helpers
    widget.scroll_tabs_left()
    widget.scroll_tabs_right()
    widget.update_tab_scroll_arrows()
    
    # Test button signal emissions
    with qtbot.waitSignal(widget.settings_requested, timeout=1000):
        widget.btn_settings.click()
        
    with qtbot.waitSignal(widget.profile_switch_requested, timeout=1000):
        widget.btn_profile.click()
        
    with qtbot.waitSignal(widget.resources_requested, timeout=1000):
        widget.btn_resources.click()

    # Test tab button click callback
    test_btn = QPushButton("Test Tab")
    test_btn.setProperty("repo_name", "Sicilian Dragon")
    repertoire_emitted = []
    widget.repertoire_changed.connect(lambda name: repertoire_emitted.append(name))
    widget._on_button_clicked(test_btn)
    assert repertoire_emitted == ["Sicilian Dragon"]

def test_training_center_widget(qtbot):
    widget = TrainingCenterWidget()
    qtbot.addWidget(widget)
    
    assert widget.txt_notation is not None
    assert widget.pie_chart is not None
    assert widget.btn_learn_new is not None
    
    # Test smart click signal
    with qtbot.waitSignal(widget.smart_clicked, timeout=1000):
        widget.btn_smart.click()
        
    # Test toggling learn new and auto continue
    toggle_emitted = []
    widget.learn_new_toggled.connect(lambda state: toggle_emitted.append(state))
    widget.btn_learn_new.click()
    assert len(toggle_emitted) > 0
    
    auto_emitted = []
    widget.auto_continue_toggled.connect(lambda state: auto_emitted.append(state))
    widget.btn_auto_continue.click()
    assert len(auto_emitted) > 0

    # Test lichess and creator request signals
    with qtbot.waitSignal(widget.lichess_requested, timeout=1000):
        widget.btn_lichess.click()
        
    with qtbot.waitSignal(widget.creator_requested, timeout=1000):
        widget.btn_creator.click()
        
    # Test state transitions
    widget.set_button_state('start', 'due')
    assert widget.btn_smart.isEnabled()
    
    widget.set_button_state('waiting_for_move', 'new')
    assert not widget.btn_smart.isEnabled()
    
    widget.set_button_state('waiting_for_move', 'due')
    assert not widget.btn_smart.isEnabled()
    
    widget.set_button_state('correct', 'due')
    
    # Test updating stats
    widget.update_stats(10, 5, {1: 3, 2: 2})
