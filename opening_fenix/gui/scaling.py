import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication

class ScaleManager:
    _instance = None
    # 928 is your Laptop's logical height (1200px minus ~40px taskbar / 1.25 scaling)
    # This ensures that on your Laptop, the scale factor is exactly 1.0.
    _base_logical_height = 928.0 
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ScaleManager, cls).__new__(cls)
            cls._instance._scale_factor = None # Lazy init
        return cls._instance

    def _init_scaling(self):
        app = QApplication.instance()
        if not app:
            # Don't cache yet, we need an app instance to detect screen height
            return 1.0

        screen = QGuiApplication.primaryScreen()
        if not screen:
            return 1.0

        # availableGeometry() automatically accounts for the Windows taskbar height!
        available_geom = screen.availableGeometry()
        available_height = available_geom.height()
        available_width = available_geom.width()
        
        # Calculate how much "bigger" the current screen is compared to your laptop
        self._scale_factor = available_height / self._base_logical_height
        
        print(f"DEBUG: ScaleManager initialized.")
        print(f"DEBUG: Screen size: {available_width}x{available_height} (Logical)")
        print(f"DEBUG: Device Pixel Ratio: {screen.devicePixelRatio()}")
        print(f"DEBUG: Base logical height: {self._base_logical_height}")
        print(f"DEBUG: Calculated Scale Factor: {self._scale_factor:.2f}")
        return self._scale_factor

            
        # Safety clamp to prevent everything from becoming too small
        if self._scale_factor < 0.5:
            self._scale_factor = 0.5


    @property
    def factor(self):
        if self._scale_factor is None:
            return self._init_scaling()
        return self._scale_factor


    def scale(self, px_value):
        """Scales a pixel value based on the current height-relative factor."""
        if px_value is None: return None
        return int(round(px_value * self.factor))


    def scale_font(self, pt_value):
        """Scales a font point size based on the current DPI factor."""
        if pt_value is None: return None
        return int(round(pt_value * self._scale_factor))

# Global helper instance
scaler = ScaleManager()

def scale(px):
    return scaler.scale(px)

def scale_font(pt):
    return scaler.scale_font(pt)
