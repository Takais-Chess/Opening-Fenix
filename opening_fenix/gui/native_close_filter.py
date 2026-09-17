import sys
from typing import Optional, Callable
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import QTimer, QCoreApplication

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes
    from PyQt6.QtCore import QAbstractNativeEventFilter

    _WM_CLOSE = 0x0010
    _WM_SYSCOMMAND = 0x0112
    _SC_CLOSE = 0xF060

    class _WindowsMSG(ctypes.Structure):
        _fields_ = [
            ('hwnd', wintypes.HWND),
            ('message', wintypes.UINT),
            ('wParam', wintypes.WPARAM),
            ('lParam', wintypes.LPARAM),
            ('time', wintypes.DWORD),
            ('pt_x', wintypes.LONG),
            ('pt_y', wintypes.LONG),
        ]

    class ModalTaskbarCloseFilter(QAbstractNativeEventFilter):
        def __init__(self, dialog: QDialog, cleanup_fn: Optional[Callable[[], None]] = None):
            super().__init__()
            self.dialog = dialog
            self.cleanup_fn = cleanup_fn
            self._triggered = False

        def nativeEventFilter(self, eventType, message):
            if self._triggered:
                return False, 0
            if eventType in ('windows_generic_MSG', 'windows_dispatcher_MSG'):
                try:
                    msg = _WindowsMSG.from_address(int(message))
                    is_close = (msg.message == _WM_CLOSE) or (
                        msg.message == _WM_SYSCOMMAND and (msg.wParam & 0xFFF0) == _SC_CLOSE
                    )
                    if is_close:
                        # Check if the close event is directed at the dialog itself (e.g. user clicked 'X' on dialog title bar)
                        target_hwnd = msg.hwnd
                        dialog_hwnd = None
                        try:
                            dialog_hwnd = int(self.dialog.winId())
                        except Exception:
                            pass

                        from PyQt6.QtWidgets import QWidget
                        target_widget = QWidget.find(target_hwnd) if target_hwnd else None

                        if (dialog_hwnd and target_hwnd == dialog_hwnd) or (
                            target_widget and (target_widget == self.dialog or self.dialog.isAncestorOf(target_widget) or isinstance(target_widget, QDialog))
                        ):
                            # Normal dialog close/cancel. Let Qt handle it via closeEvent/reject.
                            return False, 0

                        self._triggered = True
                        for w in list(QApplication.topLevelWidgets()):
                            if isinstance(w, QDialog) and w != self.dialog:
                                try:
                                    w.reject()
                                except Exception:
                                    pass
                        if self.cleanup_fn:
                            try:
                                self.cleanup_fn()
                            except Exception:
                                pass
                        try:
                            self.dialog.reject()
                        except Exception:
                            pass

                        def _close_app():
                            app = QApplication.instance()
                            if app:
                                for w in list(app.topLevelWidgets()):
                                    try:
                                        w.close()
                                    except Exception:
                                        pass
                                app.quit()

                        QTimer.singleShot(10, _close_app)
                        return True, 0
                except Exception:
                    pass
            return False, 0

def install_taskbar_close_filter(dialog: QDialog, cleanup_fn: Optional[Callable[[], None]] = None):
    if sys.platform == 'win32':
        try:
            flt = ModalTaskbarCloseFilter(dialog, cleanup_fn)
            QCoreApplication.instance().installNativeEventFilter(flt)
            return flt
        except Exception:
            return None
    return None

def uninstall_taskbar_close_filter(flt):
    if sys.platform == 'win32' and flt is not None:
        try:
            QCoreApplication.instance().removeNativeEventFilter(flt)
        except Exception:
            pass
