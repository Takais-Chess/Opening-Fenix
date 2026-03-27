import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from opening_fenix.creator.creator_window import CreatorWindow

def main():
    app = QApplication(sys.argv)
    
    # Instantiate Creator Window directly
    window = CreatorWindow()
    window.resize(1300, 850)
    window.show()
    
    def grab():
        pixmap = window.grab()
        screenshot_path = r"C:\Users\Felix\.gemini\antigravity\brain\a5b7baa4-623d-45bc-b8a8-52aa73d639eb\creator_screenshot_v4.png"
        pixmap.save(screenshot_path)
        print("SCREENSHOT_SAVED: " + screenshot_path)
        app.quit()
        
    QTimer.singleShot(1500, grab)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
