import os
import sys
from typing import Dict, Any, Optional, Tuple
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication


DISPLAY_PROFILES: Dict[str, Dict[str, Any]] = {
    # Standard HD Laptop (very common, tight vertical budget)
    "768p": {
        "name": "HD Laptop (1366x768 @ 100%)",
        "width": 1366,
        "height": 768,
        "taskbar": 40,
        "dpr": 1.0,
    },
    "hd": {
        "name": "HD Laptop (1366x768 @ 100%)",
        "width": 1366,
        "height": 768,
        "taskbar": 40,
        "dpr": 1.0,
    },
    # Full HD Laptop (1920x1080 with Windows default 125% scaling -> logical 1536x864)
    "1080p_laptop": {
        "name": "FHD Laptop (1920x1080 @ 125% DPI)",
        "width": 1536,
        "height": 864,
        "taskbar": 40,
        "dpr": 1.25,
    },
    "fhd_laptop": {
        "name": "FHD Laptop (1920x1080 @ 125% DPI)",
        "width": 1536,
        "height": 864,
        "taskbar": 40,
        "dpr": 1.25,
    },
    # Full HD Desktop (1920x1080 @ 100% scaling)
    "1080p": {
        "name": "FHD Desktop (1920x1080 @ 100% DPI)",
        "width": 1920,
        "height": 1080,
        "taskbar": 40,
        "dpr": 1.0,
    },
    "fhd": {
        "name": "FHD Desktop (1920x1080 @ 100% DPI)",
        "width": 1920,
        "height": 1080,
        "taskbar": 40,
        "dpr": 1.0,
    },
    # QHD Desktop (2560x1440 @ 100%)
    "1440p": {
        "name": "QHD Desktop (2560x1440 @ 100% DPI)",
        "width": 2560,
        "height": 1440,
        "taskbar": 40,
        "dpr": 1.0,
    },
    "2k": {
        "name": "QHD Desktop (2560x1440 @ 100% DPI)",
        "width": 2560,
        "height": 1440,
        "taskbar": 40,
        "dpr": 1.0,
    },
    # 4K UHD with typical Windows 200% scaling -> logical 1920x1080
    "4k_200": {
        "name": "4K UHD (3840x2160 @ 200% DPI)",
        "width": 1920,
        "height": 1080,
        "taskbar": 40,
        "dpr": 2.0,
    },
    # 4K UHD with Windows 150% scaling -> logical 2560x1440
    "4k_150": {
        "name": "4K UHD (3840x2160 @ 150% DPI)",
        "width": 2560,
        "height": 1440,
        "taskbar": 40,
        "dpr": 1.5,
    },
    # 4K UHD unscaled Native
    "4k": {
        "name": "4K UHD Native (3840x2160 @ 100% DPI)",
        "width": 3840,
        "height": 2160,
        "taskbar": 40,
        "dpr": 1.0,
    },
}


class ScaleManager:
    _instance = None
    # 928 is the Laptop's reference logical height (1200px minus ~40px taskbar / 1.25 scaling)
    # This ensures that on the reference display, the scale factor is exactly 1.0.
    _base_logical_height = 928.0 
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ScaleManager, cls).__new__(cls)
            cls._instance._scale_factor = None # Lazy init
            cls._instance._emulated_profile: Optional[Dict[str, Any]] = None
        return cls._instance

    def _check_env_emulation(self) -> Optional[Dict[str, Any]]:
        """Checks for OPENING_FENIX_EMULATE_SCREEN environment variable."""
        env_val = os.environ.get("OPENING_FENIX_EMULATE_SCREEN")
        if not env_val:
            return None
        
        env_clean = env_val.strip().lower()
        if env_clean in DISPLAY_PROFILES:
            profile = dict(DISPLAY_PROFILES[env_clean])
            # Optional DPR override
            dpr_env = os.environ.get("OPENING_FENIX_EMULATE_DPR")
            if dpr_env:
                try:
                    profile["dpr"] = float(dpr_env)
                except ValueError:
                    pass
            return profile
        
        # Try custom WIDTHxHEIGHT format e.g. "1366x768"
        if "x" in env_clean:
            parts = env_clean.split("x")
            try:
                w, h = int(parts[0]), int(parts[1])
                dpr = 1.0
                dpr_env = os.environ.get("OPENING_FENIX_EMULATE_DPR")
                if dpr_env:
                    dpr = float(dpr_env)
                return {
                    "name": f"Custom Emulation ({w}x{h})",
                    "width": w,
                    "height": h,
                    "taskbar": 40,
                    "dpr": dpr,
                }
            except (ValueError, IndexError):
                pass
        return None

    def set_emulation(
        self,
        width: int,
        height: int,
        taskbar: int = 40,
        dpr: float = 1.0,
        profile_name: str = "Custom Emulation"
    ):
        """Forces ScaleManager to emulate a specific screen resolution and available height."""
        self._emulated_profile = {
            "name": profile_name,
            "width": width,
            "height": height,
            "taskbar": taskbar,
            "dpr": dpr,
        }
        # Invalidate cached scale factor so it is recalculated on next access
        self._scale_factor = None
        return self.factor

    def set_emulation_profile(self, profile_key: str):
        """Forces ScaleManager to emulate a predefined display profile (e.g. '768p', '1080p_laptop', '1080p', '4k')."""
        key = profile_key.strip().lower()
        if key not in DISPLAY_PROFILES:
            raise KeyError(f"Unknown display profile '{profile_key}'. Available: {list(DISPLAY_PROFILES.keys())}")
        
        prof = DISPLAY_PROFILES[key]
        return self.set_emulation(
            width=prof["width"],
            height=prof["height"],
            taskbar=prof["taskbar"],
            dpr=prof["dpr"],
            profile_name=prof["name"]
        )

    def reset_emulation(self):
        """Disables resolution emulation and restores live hardware screen detection."""
        self._emulated_profile = None
        self._scale_factor = None

    @property
    def is_emulating(self) -> bool:
        """Returns True if resolution emulation is currently active."""
        return self._emulated_profile is not None or bool(os.environ.get("OPENING_FENIX_EMULATE_SCREEN"))

    @property
    def emulated_profile(self) -> Optional[Dict[str, Any]]:
        """Returns the active emulation profile dict or None."""
        if self._emulated_profile:
            return self._emulated_profile
        return self._check_env_emulation()

    def get_available_geometry(self) -> Tuple[int, int]:
        """Returns (available_width, available_height) accounting for emulation or current screen."""
        prof = self.emulated_profile
        if prof:
            avail_w = prof["width"]
            avail_h = max(100, prof["height"] - prof.get("taskbar", 40))
            return avail_w, avail_h
        
        app = QApplication.instance()
        if app:
            screen = QGuiApplication.primaryScreen()
            if screen:
                geom = screen.availableGeometry()
                return geom.width(), geom.height()
        
        # Fallback default
        return 1920, 1040

    def get_screen_geometry(self) -> Tuple[int, int]:
        """Returns full (width, height) accounting for emulation or current screen."""
        prof = self.emulated_profile
        if prof:
            return prof["width"], prof["height"]
        
        app = QApplication.instance()
        if app:
            screen = QGuiApplication.primaryScreen()
            if screen:
                geom = screen.geometry()
                return geom.width(), geom.height()
        
        return 1920, 1080

    def _init_scaling(self):
        # 1. Check if programmatic emulation or env emulation is active
        prof = self.emulated_profile
        if prof:
            available_width = prof["width"]
            available_height = max(100, prof["height"] - prof.get("taskbar", 40))
            dpr = prof.get("dpr", 1.0)
            self._scale_factor = available_height / self._base_logical_height
            if self._scale_factor < 0.5:
                self._scale_factor = 0.5
            return self._scale_factor

        # 2. Otherwise detect from Qt screen
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
        
        # Calculate how much "bigger" the current screen is compared to reference
        self._scale_factor = available_height / self._base_logical_height
        
        # Safety clamp to prevent everything from becoming too small
        if self._scale_factor < 0.5:
            self._scale_factor = 0.5

        return self._scale_factor

    @property
    def factor(self):
        if self._scale_factor is None:
            self._init_scaling()
            
        if self._scale_factor is None or self._scale_factor < 0.5:
            self._scale_factor = 0.5
            
        return self._scale_factor

    def scale(self, px_value):
        """Scales a pixel value based on the current height-relative factor."""
        if px_value is None: return None
        return int(round(px_value * self.factor))

    def scale_font(self, pt_value):
        """Scales a font point size based on the current DPI factor."""
        if pt_value is None: return None
        return int(round(pt_value * self.factor))


# Global helper instance
scaler = ScaleManager()

def scale(px):
    return scaler.scale(px)

def scale_font(pt):
    return scaler.scale_font(pt)

def set_emulation(width: int, height: int, taskbar: int = 40, dpr: float = 1.0, profile_name: str = "Custom Emulation"):
    return scaler.set_emulation(width, height, taskbar, dpr, profile_name)

def set_emulation_profile(profile_key: str):
    return scaler.set_emulation_profile(profile_key)

def reset_emulation():
    return scaler.reset_emulation()

def get_available_geometry():
    return scaler.get_available_geometry()

def get_screen_geometry():
    return scaler.get_screen_geometry()

