import sys
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow

from opening_fenix.gui.styles import bring_window_to_front


def _get_app():
    return QApplication.instance() or QApplication(sys.argv)


def _process_events_briefly(app, ms=50):
    loop_done = False

    def _stop():
        nonlocal loop_done
        loop_done = True

    QTimer.singleShot(ms, _stop)
    while not loop_done:
        app.processEvents()


def test_bring_window_to_front_none_is_noop():
    bring_window_to_front(None)


def test_bring_window_to_front_restores_minimized_dialog():
    app = _get_app()
    dlg = QDialog(None)
    dlg.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.WindowMinMaxButtonsHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    dlg.setModal(False)
    dlg.resize(300, 200)
    dlg.show()
    _process_events_briefly(app)

    dlg.showMinimized()
    _process_events_briefly(app)
    assert dlg.isMinimized()

    bring_window_to_front(dlg)
    _process_events_briefly(app)
    assert not dlg.isMinimized()
    assert dlg.isVisible()
    assert dlg.isActiveWindow()
    dlg.close()


def test_bring_window_to_front_preserves_maximized_state_when_restoring():
    app = _get_app()
    dlg = QDialog(None)
    dlg.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.WindowMinMaxButtonsHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    dlg.setModal(False)
    dlg.showMaximized()
    _process_events_briefly(app)
    assert dlg.isMaximized()

    dlg.showMinimized()
    _process_events_briefly(app)
    assert dlg.isMinimized()

    bring_window_to_front(dlg)
    _process_events_briefly(app)
    assert not dlg.isMinimized()
    assert dlg.isMaximized()
    dlg.close()


def test_bring_window_to_front_activates_background_dialog():
    app = _get_app()
    main = QMainWindow()
    main.resize(400, 300)
    main.show()

    settings = QDialog(main)
    settings.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.WindowMinMaxButtonsHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    settings.setModal(False)
    settings.resize(320, 220)
    settings.show()

    task_center = QDialog(None)
    task_center.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.WindowMinMaxButtonsHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    task_center.setModal(False)
    task_center.resize(320, 220)
    task_center.show()
    _process_events_briefly(app)

    # Put task_center in the background by activating settings
    bring_window_to_front(settings)
    _process_events_briefly(app)
    assert settings.isActiveWindow()
    assert not task_center.isActiveWindow()

    # Now bring task_center back to the front
    bring_window_to_front(task_center)
    _process_events_briefly(app)
    assert task_center.isActiveWindow()
    assert not settings.isActiveWindow()

    task_center.close()
    settings.close()
    main.close()
