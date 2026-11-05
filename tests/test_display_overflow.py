import pytest
from opening_fenix.gui.scaling import (
    scaler,
    set_emulation_profile,
    reset_emulation,
    get_available_geometry,
    DISPLAY_PROFILES,
)
from scripts.display_overflow_harness import DisplayOverflowHarness


@pytest.fixture(autouse=True)
def clean_emulation():
    yield
    reset_emulation()


@pytest.mark.parametrize("profile_key", ["768p", "1080p_laptop", "1080p"])
def test_dialog_minimum_sizes_fit_viewports(profile_key):
    """
    Ensures no dialog has a minimumSize that exceeds the available screen viewport
    on HD (768p), FHD Laptop (125% DPI), and FHD Desktop (100% DPI).
    """
    harness = DisplayOverflowHarness(profiles=[profile_key])
    catalog = harness.get_component_catalog()
    set_emulation_profile(profile_key)
    avail_w, avail_h = get_available_geometry()

    for comp_key, comp_title, factory in catalog:
        scaler._scale_factor = None
        widget = factory()
        try:
            min_w = widget.minimumSize().width()
            min_h = widget.minimumSize().height()
            
            assert min_h <= avail_h, (
                f"{comp_title} minimum height ({min_h}px) exceeds {profile_key} "
                f"available height ({avail_h}px) by {min_h - avail_h}px!"
            )
            assert min_w <= avail_w, (
                f"{comp_title} minimum width ({min_w}px) exceeds {profile_key} "
                f"available width ({avail_w}px) by {min_w - avail_w}px!"
            )
        finally:
            widget.close()
            widget.deleteLater()
            harness.app.processEvents()
