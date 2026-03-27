import sys
import os
import json
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Add project root to path
sys.path.append(r"c:\Users\Felix\Downloads\Opening Fenix V2")

from opening_fenix.gui.main_window import MainWindow
from opening_fenix.core.data_tools import get_user_dir

app = QApplication(sys.argv)

config_path = os.path.join(get_user_dir(), "config.json")
profile_name = "Default"
if os.path.exists(config_path):
    with open(config_path, "r") as f:
        config = json.load(f)
        profile_name = config.get("last_profile", "Default")

window = MainWindow(profile_name)
window.show()

def take_shot():
    # Wait until the window is fully initialized
    if window.btn_smart.isEnabled():
        window.btn_smart.click()
    else:
        # Sometimes the button is disabled right at start if no moves are selected
        pass
        
    def grab():
        pixmap = window.grab()
        screenshot_path = r"C:\Users\Felix\.gemini\antigravity\brain\a5b7baa4-623d-45bc-b8a8-52aa73d639eb\contrast_screenshot_v6.png"
        pixmap.save(screenshot_path)
        print("SCREENSHOT_SAVED: " + screenshot_path)
        app.quit()
        
    QTimer.singleShot(1500, grab)

QTimer.singleShot(1000, take_shot)

sys.exit(app.exec())
