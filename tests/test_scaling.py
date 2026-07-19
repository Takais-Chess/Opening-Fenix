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
