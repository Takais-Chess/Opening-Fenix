import os
import pytest
from opening_fenix.gui.styles import (
    get_checkmark_icon_path,
    get_indicator_style,
    get_creator_window_style,
    get_main_window_style,
    get_repo_settings_style,
    get_export_dialog_style,
    get_bw_glass_style,
    get_login_dialog_style,
)

def test_checkmark_svg_asset_exists():
    path = get_checkmark_icon_path()
    assert os.path.exists(path), f"Checkmark SVG does not exist at {path}"
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<svg" in content
    assert "polyline" in content or "path" in content

def test_indicator_style_generator():
    style = get_indicator_style()
    assert "QCheckBox::indicator" in style
    assert "QTreeWidget::indicator" in style
    assert "QTreeWidget::indicator:checked" in style
    assert "checkmark.svg" in style
    assert "border-radius" in style

def test_styles_include_indicators():
    creator_style = get_creator_window_style()
    assert "QTreeWidget::indicator" in creator_style
    assert "checkmark.svg" in creator_style

    main_style = get_main_window_style()
    assert "QCheckBox::indicator" in main_style
    assert "checkmark.svg" in main_style

    bw_style = get_bw_glass_style()
    assert "QCheckBox::indicator" in bw_style
    assert "checkmark.svg" in bw_style

    repo_style = get_repo_settings_style()
    assert "QCheckBox::indicator" in repo_style

    export_style = get_export_dialog_style()
    assert "QCheckBox::indicator" in export_style

    login_style = get_login_dialog_style()
    assert "QCheckBox::indicator" in login_style
