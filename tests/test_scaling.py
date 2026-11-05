import pytest
from opening_fenix.gui.scaling import ScaleManager, scale, scale_font

def test_scale_manager_clamp():
    """Verify that ScaleManager factor clamp works and prevents factor from falling below 0.5."""
    manager = ScaleManager()
    
    # Force a very low factor
    manager._scale_factor = 0.1
    
    # Reading factor property should trigger clamp
    assert manager.factor == 0.5

def test_scale_manager_normal_value():
    """Verify that ScaleManager preserves normal scale factors above 0.5."""
    manager = ScaleManager()
    
    # Inject normal scale factor
    manager._scale_factor = 1.25
    
    assert manager.factor == 1.25

def test_scale_and_scale_font_helpers():
    """Verify that scale and scale_font functions resolve correctly using the manager factor."""
    manager = ScaleManager()
    manager._scale_factor = 1.0
    
    assert scale(10) == 10
    assert scale_font(12) == 12
    
    manager._scale_factor = 0.5
    assert scale(10) == 5
    assert scale_font(12) == 6

def test_scale_manager_emulation():
    """Verify that resolution emulation correctly alters scale factor and geometry."""
    import os
    from opening_fenix.gui.scaling import (
        set_emulation_profile,
        set_emulation,
        reset_emulation,
        get_available_geometry,
        get_screen_geometry,
        scaler,
    )

    try:
        # Test 768p profile
        set_emulation_profile("768p")
        assert scaler.is_emulating is True
        # available height: 768 - 40 = 728; factor = 728 / 928 = ~0.784
        assert abs(scaler.factor - (728.0 / 928.0)) < 0.001
        assert get_available_geometry() == (1366, 728)
        assert get_screen_geometry() == (1366, 768)

        # Test 1080p profile
        set_emulation_profile("1080p")
        # available height: 1080 - 40 = 1040; factor = 1040 / 928 = ~1.1207
        assert abs(scaler.factor - (1040.0 / 928.0)) < 0.001
        assert get_available_geometry() == (1920, 1040)
        assert get_screen_geometry() == (1920, 1080)

        # Test custom emulation
        set_emulation(1280, 720, taskbar=30)
        # available height: 720 - 30 = 690; factor = 690 / 928 = ~0.7435
        assert abs(scaler.factor - (690.0 / 928.0)) < 0.001
        assert get_available_geometry() == (1280, 690)
        assert get_screen_geometry() == (1280, 720)

        # Reset emulation
        reset_emulation()
        assert scaler.is_emulating is False

        # Test env variable emulation
        os.environ["OPENING_FENIX_EMULATE_SCREEN"] = "768p"
        scaler._scale_factor = None  # refresh
        assert scaler.is_emulating is True
        assert abs(scaler.factor - (728.0 / 928.0)) < 0.001
    finally:
        os.environ.pop("OPENING_FENIX_EMULATE_SCREEN", None)
        reset_emulation()

