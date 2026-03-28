import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture
def qapp():
    # We must have a QApplication for any UI tests
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def test_main_window_has_logger_import(qapp):
    """
    Verifies that the MainWindow module correctly imports the centralized logger.
    This directly prevents the NameError: name 'logger' is not defined.
    """
    try:
        from opening_fenix.gui.main_window import logger as mw_logger
        from opening_fenix.core.logger import logger as core_logger
        
        assert mw_logger is core_logger, "MainWindow is not using the centralized logger from core.logger"
        assert mw_logger is not None
    except ImportError as e:
        pytest.fail(f"Failed to import logger in MainWindow: {e}")
    except AttributeError:
        pytest.fail("MainWindow is missing the 'logger' symbol in its namespace")

def test_main_window_module_loadable(qapp):
    """
    Ensures the MainWindow module can be loaded without any NameErrors or ImportErrors.
    """
    try:
        import opening_fenix.gui.main_window
    except Exception as e:
        pytest.fail(f"MainWindow module failed to load: {e}")

if __name__ == "__main__":
    import sys
    # For manual verification
    try:
        from opening_fenix.gui.main_window import logger
        print("PASS: logger is available in main_window.py")
    except Exception as e:
        print(f"FAIL: {e}")
        sys.exit(1)
