import pytest
from PyQt6.QtWidgets import QMessageBox
from opening_fenix.gui.dialogs.export_dialog import ExportDialog
import chess

def test_estimate_pgn_export_backend(complex_backend):
    """Test estimate_pgn_export returns valid estimations under different modes."""
    # Test Mode 2 (Default cutoff)
    est_m2 = complex_backend.estimate_pgn_export(transpos_mode=2)
    assert isinstance(est_m2, dict)
    assert "estimated_moves" in est_m2
    assert "transposition_cuts" in est_m2
    assert "expansion_factor" in est_m2
    assert "estimated_size_mb" in est_m2
    assert "risk_level" in est_m2
    assert est_m2["expansion_factor"] == 1.0
    assert est_m2["risk_level"] == "safe"
    assert est_m2["estimated_moves"] >= 0

    # Test Mode 0 (No cutoff)
    est_m0 = complex_backend.estimate_pgn_export(transpos_mode=0)
    assert est_m0["estimated_moves"] >= est_m2["estimated_moves"]
    assert est_m0["expansion_factor"] >= 1.0

    # Test with level limit
    est_lvl = complex_backend.estimate_pgn_export(transpos_mode=2, max_l=1)
    assert est_lvl["estimated_moves"] <= est_m2["estimated_moves"]

def test_estimate_pgn_export_empty_backend():
    """Test estimate_pgn_export when backend has no active session."""
    from opening_fenix.creator.creator_window import CreatorBackend
    empty_backend = CreatorBackend(is_test=True)
    est = empty_backend.estimate_pgn_export()
    assert est["estimated_moves"] == 0
    assert est["risk_level"] == "safe"

def test_export_dialog_banner_updates(qtbot, complex_backend):
    """Test ExportDialog dynamic banner updates when options change."""
    dialog = ExportDialog(complex_backend)
    qtbot.addWidget(dialog)
    dialog.show()

    # Initial state: PGN is checked, Mode 2 selected
    assert not dialog.banner_est.isHidden()
    assert "Geschätzte Größe" in dialog.lbl_est_title.text() or "Estimated size" in dialog.lbl_est_title.text()

    # Switch to DB: banner should hide
    dialog.r_db.setChecked(True)
    assert not dialog.banner_est.isVisible()

    # Switch back to PGN: banner should show
    dialog.r_pgn.setChecked(True)
    assert dialog.banner_est.isVisible()

    # Switch to Mode 0 (Index 0)
    dialog.combo_transpos.setCurrentIndex(0)
    assert dialog.banner_est.isVisible()

def test_export_dialog_critical_warning_confirmation(qtbot, complex_backend, monkeypatch):
    """Test confirmation dialog prompt when exporting with critical risk level."""
    dialog = ExportDialog(complex_backend)
    qtbot.addWidget(dialog)

    dialog.combo_transpos.setCurrentIndex(0)
    # Simulate critical risk estimation
    dialog.current_estimation = {
        "estimated_moves": 750000,
        "transposition_cuts": 699,
        "expansion_factor": 25.0,
        "estimated_size_mb": 45.0,
        "risk_level": "critical",
        "base_moves": 27000
    }
    dialog.update_estimation = lambda: None  # prevent overwriting simulated estimation

    # 1. User clicks No (Abort)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    dialog.on_accept()
    # Dialog should NOT have accepted
    assert dialog.result_data is None

    # 2. User clicks Yes (Proceed)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    dialog.on_accept()
    # Dialog should have accepted
    assert dialog.result_data is not None
    assert dialog.result_data[0] == "pgn"
    assert dialog.result_data[2] == 0
    assert dialog.result_data[5]["estimated_moves"] == 750000
